#!/bin/bash
# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

#SBATCH --ntasks-per-node=2
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:1

#SBATCH --mem-per-cpu=16000

#SBATCH --output=scripts/slurm/logs/%x_%j.out
#SBATCH --error=scripts/slurm/logs/%x_%j.err

#SBATCH --signal=B:USR1@900

echo "Job: $SLURM_JOB_ID on $(hostname)"

# --- CONFIGURATION ---
WANDB_PROJECT=${WANDB_PROJECT:-puffer_drive}
REPO_DIR="$PWD"  # Remember where we started (shared storage)
# --- 1. File System Setup ---

# A. Define Persistent Destination (The "Vault")
# Structure: /path/to/results/project_name/job_id/
if [[ -n "$WANDB_SWEEP_ID" ]]; then
    FINAL_LOG_DIR="$RESULTS_DIR/$WANDB_PROJECT/$WANDB_SWEEP_ID/$SLURM_JOB_ID"
else
    FINAL_LOG_DIR="$RESULTS_DIR/$WANDB_PROJECT/$SLURM_JOB_ID"
fi

mkdir -p "$FINAL_LOG_DIR"

# B. Define Local Fast Storage (The "Workbench")
LOCAL_SCRATCH="$TMPDIR"
LOCAL_DATA_DIR="$LOCAL_SCRATCH/data"
LOCAL_OUTPUT_DIR="$LOCAL_SCRATCH/output"
LOCAL_CODE_DIR="$LOCAL_SCRATCH/code"



# --- 2. CONFIGURE CACHES (The Fix) ---

# A. Master Cache: Persistent storage on shared drive
# This is where we keep the "single source of truth" for downloaded wheels.
MASTER_CACHE_DIR="$REPO_DIR/.uv_cache"
mkdir -p "$MASTER_CACHE_DIR"

# B. Active Cache: Local Scratch
# We tell 'uv' to use this local directory. Since this folder is private 
# to this specific job, there will be no locking conflicts with other jobs.
export UV_CACHE_DIR="$LOCAL_SCRATCH/.uv_cache"


# --- 3. BOOTSTRAP UV ---

export UV_INSTALL_DIR="$REPO_DIR/bin"
mkdir -p "$UV_INSTALL_DIR"

# Check if uv binary exists in our local bin
if [ ! -f "$UV_INSTALL_DIR/uv" ]; then
    echo ">>> 'uv' not found. Installing to $UV_INSTALL_DIR..."
    # We use 'flock' to prevent race conditions during binary installation
    (
        flock -x 200
        if [ ! -f "$UV_INSTALL_DIR/uv" ]; then
             curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$UV_INSTALL_DIR" sh
        fi
    ) 200>"$UV_INSTALL_DIR/uv.lock"
fi

# Add our local uv to the path
export PATH="$UV_INSTALL_DIR:$PATH"
echo ">>> Using uv from: $(which uv)"


# --- 4. PREPARE LOCAL DIRS & STAGE CACHE ---

mkdir -p "$LOCAL_DATA_DIR"
mkdir -p "$LOCAL_OUTPUT_DIR"
mkdir -p "$LOCAL_CODE_DIR"

echo ">>> Staging UV Cache to Local Scratch..."
# Sync the Shared Cache -> Local Cache
# This makes the cache available locally so 'uv' doesn't need to re-download files,
# but it performs file locks on the local SSD, avoiding the network timeout.
rsync -ahq "$MASTER_CACHE_DIR/" "$UV_CACHE_DIR/"

# A. Stage Data
echo "Staging input data to $LOCAL_DATA_DIR..."
# 1. Extract names
TAR_NAME=$(basename "$DRIVE_BINARIES_DATA_ROOT_TAR")
LOCAL_TAR_PATH="$LOCAL_DATA_DIR/$TAR_NAME"

# 2. Copy the tarball to the local directory
echo "Copying $TAR_FILENAME..."
cp "$DRIVE_BINARIES_DATA_ROOT_TAR" "$LOCAL_TAR_PATH"

EXTRACTED_FOLDER_NAME=$(tar -ztf "$LOCAL_TAR_PATH" | head -n 1 | cut -d/ -f1)

# 3. Extract the tarball
echo "Extracting $LOCAL_DATA_DIR/$TAR_NAME to $LOCAL_DATA_DIR"
tar -xzf "$LOCAL_TAR_PATH" -C "$LOCAL_DATA_DIR"

# 4. Cleanup (Optional: remove the compressed file to save space)
rm "$LOCAL_TAR_PATH"

# 5. Update the Root Variable dynamically
export DRIVE_BINARIES_DATA_ROOT="$LOCAL_DATA_DIR/$EXTRACTED_FOLDER_NAME/"

# --- BRANCH SELECTION ---
BRANCH_TO_USE="${TARGET_BRANCH:-main}"
# Create a unique temporary path for this specific job's source code
TEMP_WORKTREE="$REPO_DIR/../temp_worktree_$SLURM_JOB_ID"

echo "Creating isolated worktree for branch: $TARGET_BRANCH at $TEMP_WORKTREE"

# 1. Create the worktree (this is nearly instantaneous)
# This checks out the branch into a brand new folder
git -C "$REPO_DIR" fetch origin
git -C "$REPO_DIR" worktree add -f "$TEMP_WORKTREE" "$TARGET_BRANCH"

# --- B. Stage Code ---
echo "Staging code to local compute node..."

# 2. Sync from the isolated worktree to the local SSD
rsync -ahq \
    --exclude '.git' \
    --exclude 'data' \
    --exclude 'wandb' \
    --exclude '.venv' \
    "$TEMP_WORKTREE/" "$LOCAL_CODE_DIR/"

# 3. Cleanup the worktree immediately after rsync (no longer needed)
git -C "$REPO_DIR" worktree remove -f "$TEMP_WORKTREE"

# Move into the local code directory for execution
cd "$LOCAL_CODE_DIR" || exit 1


# A. Create fresh venv
uv venv .venv

# B. Activate
source .venv/bin/activate

# C. Install Dependencies
# This uses the shared UV_CACHE_DIR, so it's super fast after the first run
echo ">>> Installing dependencies..."
uv pip install -e .

# D. Compile C Extensions
echo ">>> Compiling C extensions..."
python setup.py build_ext --inplace --force

# --- 5. EXECUTION SETUP ---

# Tell WandB to write logs to local scratch, not shared storage
export WANDB_DIR="$LOCAL_OUTPUT_DIR"
export WANDB_CACHE_DIR="$LOCAL_SCRATCH/.cache/wandb"
mkdir -p "$WANDB_CACHE_DIR"

# --- 3. Safety Mechanism (The Trap) ---
# This runs when the job ends (successfully) OR if it crashes/times out.
function save_and_cleanup() {
    exec 1>&3 2>&4

    echo "------------------------------------------------"
    echo "Kill all running processes"

    for pid in "${pids[@]}"; do
        kill -USR1 $pid
        echo "Killed process $pid"
    done

    echo "------------------------------------------------"
    echo "Syncing results from Compute Node to Persistent Storage..."
    
    # Rsync from Local Fast Storage -> Persistent Storage
    mkdir -p "$FINAL_LOG_DIR/output"
    #mkdir -p "$FINAL_LOG_DIR/code"

    rsync -av "$LOCAL_OUTPUT_DIR/" "$FINAL_LOG_DIR/output"
    echo "Output Sync completed"
    #rsync -av "$LOCAL_CODE_DIR/" "$FINAL_LOG_DIR/code"
    #echo "Code Sync completed"

    echo "Cleaning up local scratch..."
    rm -rf "$LOCAL_DATA_DIR"
    rm -rf "$LOCAL_OUTPUT_DIR"
    rm -rf "$LOCAL_CODE_DIR"

    echo "Job Complete. Results saved to $FINAL_LOG_DIR"
    echo "------------------------------------------------"
}

echo "Activating Trigger..."
# Trigger this function on EXIT (normal finish), SIGTERM (scancel), or SIGUSR1 (timeout warning)
trap save_and_cleanup SIGTERM SIGUSR1

# C. Setup Local Logging (NEW)
# ---------------------------------------------------------
# Define a log file on the compute node's SSD
LOCAL_LOG_FILE="$LOCAL_OUTPUT_DIR/runtime_log.txt"

# Redirect all future standard output (1) and standard error (2)
# DIRECTLY to the local file.
# NOTE: This will make the SLURM .out file on the network drive empty
# (except for lines printed before this command).
echo "Redirecting all logs to compute node: $LOCAL_LOG_FILE"
exec > "$LOCAL_LOG_FILE"
# ---------------------------------------------------------



# --- 4. Execution ---

# We add the output directory to the extra_args so the python script knows where to write
# We assume your python script accepts '--data-dir' or '--output-dir'
# If not, you may need to adjust the flag name below.
OUTPUT_ARGS=("--train.data-dir" "$LOCAL_OUTPUT_DIR")

pids=()

if [[ -n "$WANDB_SWEEP_ID" ]]; then
    echo ">>> SWEEP MODE DETECTED <<<"
    # Note: We append OUTPUT_ARGS to "$@"
    python scripts/slurm/sweep_runner.py \
        --wandb_sweep_id "$WANDB_SWEEP_ID" \
        --wandb_group "$WANDB_GROUP" \
        --wandb_project "$WANDB_PROJECT" \
        "${OUTPUT_ARGS[@]}" "$@" &
    pids+=($!)

else
    echo ">>> STANDARD TRAINING MODE <<<"
    
    puffer train puffer_drive "${OUTPUT_ARGS[@]}" "$@" &
fi


for idx in "${!pids[@]}"; do
    pid=${pids[$idx]}
    # wait blocks the script until this specific PID finishes
    wait $pid
    status=$?
    echo "Agent $idx (PID $pid) exited with status $status"
    # Remove the element from the array
    unset "pids[$idx]"
done



echo "🧹 Job finished. Performing cleanup."

save_and_cleanup

echo "Exiting..."

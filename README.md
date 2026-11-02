# PufferDrive

## Scene editor

![PufferDrive scene editor](demo/assets/screenshot.png)

This repository proposes a new **interactive scene editor** for running and testing scenes in
PufferDrive. It is a browser app (built with [Reflex](https://reflex.dev), in [`demo/`](demo/))
that loads a map binary, rolls out a trained policy in the simulator, and lets you edit the
scene — move agents, retarget goals, add or delete controlled and parked vehicles, draw expert
trajectories — then re-simulate and scrub through the result. A second "ghost" environment can
run a different policy on the same scene for side-by-side comparison, and any edited scene can be
saved to JSON and reloaded later. Unlike the existing [WOMD scenario editor](docs/src/scene-editor.md),
which only edits scenario JSON, this editor runs the actual PufferDrive simulator and policies.

### Highlights

- **Scenario and track editor** — author stress tests on real maps by moving or inserting parked
  obstacles and placing controlled vehicles with custom poses, goals, and expert trajectories
  (e.g. narrow corridors, slaloms, emergency braking).
- **Closed-loop re-simulation** — every edit is rolled out with a trained policy in the
  PufferDrive simulator, so you see how the policy actually reacts.
- **Real-time kinematics dashboard** — plots the realized acceleration and jerk of the selected
  vehicle at every step against the passenger-comfort limits, with exceedances highlighted in red.
- **Multi-model auditing** — run a second "ghost" policy on the same scene and compare the two
  rollouts side by side or overlaid on one map, with synchronized timelines.
- **Shareable scenes** — save edited scenes to JSON and reload them later or on another
  machine.

### Quick start

```bash
uv venv && source .venv/bin/activate
uv pip install -e .
uv pip install -r demo/requirements.txt
export DRIVE_BINARIES_DATA_ROOT=/path/to/binaries   # contains training/ validation/ testing/
cd demo && ./run.sh
```

Then open <http://localhost:3000>. `run.sh` builds the C extension, links in
`pufferlib/resources`, and launches the app. If `DRIVE_BINARIES_DATA_ROOT` is unset, the binaries
bundled in `pufferlib/resources/drive/binaries` are used.

### How to use

- **Header** — pick a Config profile, a Map, and a Policy, then hit **Load**. The second policy
  dropdown drives the ghost environment.
- **Toolbar** — `Pan`, `Select`, `Move`, `Goals`, `Agent` (add a controlled agent), `Static` (add
  a parked vehicle). `Both` applies edits to the primary and ghost environment at once.
- **Timeline** — scrub, play/pause, and loop the rollout to see how the policy reacts to your edits.
- **Save scenes** — the export dialog writes the edited scene to `demo/scenarios/<name>.json`;
  saved scenes reappear in the Map dropdown marked with ★. Example scenarios (bottleneck,
  congestion, dead end, distractor, T-bone) are shipped in [`demo/scenarios/`](demo/scenarios/)
  and need a `DRIVE_BINARIES_DATA_ROOT` with a populated `testing/` split.
- **Configure** — the maps and policies on offer come from profile inis in `demo/config/`; copy
  [`demo/config/example.ini`](demo/config/example.ini) to add your own checkpoints.

See [demo/README.md](demo/README.md) for environment variables, the profile format, remote access
over an SSH tunnel, and troubleshooting.

---

<img align="left" style="width:260px" src="https://github.com/Emerge-Lab/PufferDrive/blob/main/pufferlib/resources/drive/pufferdrive_20fps_long.gif" width="288px">

**PufferDrive is a fast and friendly driving simulator to train and test RL-based models.**

<br>
<br>
<br>
<br>
<br>
<br>
<br>
<br>
<br>
<br>

---


**Docs**: https://emerge-lab.github.io/PufferDrive

---

## Installation

Clone the repo
```bash
https://github.com/Emerge-Lab/PufferDrive.git
```

Make a venv (`uv venv`), activate the venv
```
source .venv/bin/activate
```

Inside the venv, install the dependencies
```
uv pip install -e .
```

Compile the C code
```
python setup.py build_ext --inplace --force
```
Run this while your virtual environment is active so the extension is built against the right interpreter.

To test your setup, you can run
```
puffer train puffer_drive
```
See also the [puffer docs](https://puffer.ai/docs.html).


## Quick start

Start a training run
```
puffer train puffer_drive
```

## Dataset

<details>
<summary>Downloading and using data</summary>

### Data preparation

To train with PufferDrive, you need to convert JSON files to map binaries. Run the following command with the path to your data folder:

```bash

export DRIVE_BINARIES_DATA_ROOT=your/path/to/binaries
export DRIVE_DATA_ROOT=your/path/to/jsons

python pufferlib/ocean/drive/drive.py
```

### Downloading Waymo Data

You can download the WOMD data from Hugging Face in two versions:

- **Mini dataset**: [GPUDrive_mini](https://huggingface.co/datasets/EMERGE-lab/GPUDrive_mini) contains 1,000 training files and 300 test/validation files
- **Medium dataset**: [10,000 files from the training dataset](https://huggingface.co/datasets/daphne-cornelisse/pufferdrive_train)
- **Large dataset**: [GPUDrive](https://huggingface.co/datasets/EMERGE-lab/GPUDrive) contains 100,000 unique scenes

**Note**: Replace 'GPUDrive_mini' with 'GPUDrive' in your download commands if you want to use the full dataset.

### Additional Data Sources

For more training data compatible with PufferDrive, see [ScenarioMax](https://github.com/valeoai/ScenarioMax). The GPUDrive data format is fully compatible with PufferDrive.
</details>


## Visualizer

<details>
<summary>Dependencies and usage</summary>

## Local rendering

To launch an interactive renderer, first build:
```
bash scripts/build_ocean.sh drive local
```

then launch:
```bash
./drive
```
this will run `demo()` with an existing model checkpoint.

## Headless server setup

Run the Raylib visualizer on a headless server and export as .mp4. This will rollout the pre-trained policy in the env.

### Install dependencies

```bash
sudo apt update
sudo apt install ffmpeg xvfb
```

For HPC (There are no root privileges), so install into the conda environment
```bash
conda install -c conda-forge xorg-x11-server-xvfb-cos6-x86_64
conda install -c conda-forge ffmpeg
```

- `ffmpeg`: Video processing and conversion
- `xvfb`: Virtual display for headless environments

### Build and run

1. Build the application:
```bash
bash scripts/build_ocean.sh visualize local
```

2. Run with virtual display:
```bash
xvfb-run -s "-screen 0 1280x720x24" ./visualize
```

The `-s` flag sets up a virtual screen at 1280x720 resolution with 24-bit color depth.

---

> To force a rebuild, you can delete the cached compiled executable binary using `rm ./visualize`.

---

</details>


## Interactive demo

The browser-based scene editor lives in `demo/`. See [Scene editor](#scene-editor) at the top
of this README for a quick start, and [demo/README.md](demo/README.md) for the full setup.

## Benchmarks

### Distributional realism

We provide a PufferDrive implementation of the [Waymo Open Sim Agents Challenge (WOSAC)](https://waymo.com/open/challenges/2025/sim-agents/) for fast, easy evaluation of how well your trained agent matches distributional properties of human behavior. See documentation [here](https://emerge-lab.github.io/PufferDrive/wosac/).

WOSAC evaluation with random policy:
```bash
puffer eval puffer_drive --eval.wosac-realism-eval True
```

WOSAC evaluation with your checkpoint (must be .pt file):
```bash
puffer eval puffer_drive --eval.wosac-realism-eval True --load-model-path <your-trained-policy>.pt
```

### Human-compatibility

You may be interested in how compatible your agent is with human partners. For this purpose, we support an eval where your policy only controls the self-driving car (SDC). The rest of the agents in the scene are stepped using the logs. While it is not a perfect eval since the human partners here are static, it will still give you a sense of how closely aligned your agent's behavior is to how people drive. You can run it like this:
```bash
puffer eval puffer_drive --eval.human-replay-eval True --load-model-path <your-trained-policy>.pt
```

## Development

<details><summary>Documentation and browser demo</summary>

**Docs**

A browsable documentation site now lives under `docs/` and is configured with mkbooks. To preview locally:
```
brew install mdbook
mdbook serve --open docs
```
Open the served URL to see a local version of the docs.

**Interactive demo**

To edit the browser demo, follow these steps:
- Download [emscripten](https://github.com/emscripten-core/emscripten)
- emscripten install latest
- Activate: `source emsdk/emsdk_env.sh`
- Run `bash scripts/build_ocean.sh drive web`
- This generates a number of `game*` files, move them to `assets/` to include them on the webpage

</details>


## Citation

If you use PufferDrive in your research, please cite:
```bibtex
@software{pufferdrive2025github,
  author = {Daphne Cornelisse* and Spencer Cheng* and Pragnay Mandavilli and Julian Hunt and Kevin Joseph and Waël Doulazmi and Aditya Gupta and Eugene Vinitsky},
  title = {{PufferDrive}: A Fast and Friendly Driving Simulator for Training and Evaluating {RL} Agents},
  url = {https://github.com/Emerge-Lab/PufferDrive},
  version = {2.0.0},
  year = {2025},
}
```

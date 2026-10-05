# PufferDrive Demo

A browser-based interactive viewer for PufferDrive scenarios, built with
[Reflex](https://reflex.dev). It loads a map binary, rolls out a trained policy, and lets you
edit the scene — move agents, retarget goals, add or delete vehicles, draw expert trajectories —
then re-simulate and scrub through the result. A second ("ghost") environment can run a
different policy on the same scene for side-by-side comparison, and any edited scene can be
saved to JSON and reloaded later.

---

## Setup

### 1. Install the repository

Follow the install steps in the [top-level README](../README.md): create and activate a
virtual environment, then install the package in editable mode.

```bash
cd ..
python -m venv .venv          # or: uv venv
source .venv/bin/activate
pip install -e .              # or: uv pip install -e .
```

### 2. Install the demo's own dependencies

```bash
pip install -r demo/requirements.txt
```

### 3. Build the C extension

The demo imports the compiled `pufferlib.ocean.drive` environment, so it must be built
against the interpreter of the active virtual environment:

```bash
python setup.py build_ext --inplace --force
```

`run.sh` does this for you on every launch — it is cheap when nothing changed. Build it by
hand whenever you change the C sources (`drive.h`, `binding.c`) outside of `run.sh`.

> A **stale `.so`** is the most common source of confusing demo behaviour: newly added
> observation fields or env kwargs are silently ignored by an old binding. When something
> looks inexplicably wrong, rebuild with `--force` first.

### 4. Point the demo at your map binaries

The demo needs a directory of Waymo map binaries laid out as
`<root>/{training,validation,testing}/map_NNNNNN.bin`. See
[Dataset](../README.md#dataset) in the top-level README for downloading the data and
converting the JSON scenarios into binaries.

**Export the binaries root before launching** — this is the one setting you almost always
have to set:

```bash
export DRIVE_BINARIES_DATA_ROOT=/path/to/your/binaries
```

If you leave it unset, the demo falls back to `resources/drive/binaries`, i.e. the binaries
shipped in `pufferlib/resources/drive/binaries` of this checkout.

`resources` inside this directory is a **symlink to `../pufferlib/resources`** — it is not
tracked by git, and `run.sh` recreates it if missing. To create it by hand:

```bash
ln -sfn ../pufferlib/resources resources
```

### 5. Run

```bash
cd demo
./run.sh
```

Then open <http://localhost:3000>.

---

## Environment variables

All are optional; export them before running `run.sh`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DRIVE_BINARIES_DATA_ROOT` | `resources/drive/binaries` | Root of the map binaries, containing `training/`, `validation/`, `testing/`. |
| `DRIVE_CONFIG_DIR` | `config` | Directory scanned for demo profile `*.ini` files (populates the **Config** dropdown). |
| `DRIVE_SCENARIOS_DIR` | `scenarios` | Where saved scenario JSON files are read from and written to. |
| `HOST_IP` | `localhost` | Host the browser uses to reach the backend. Set to the machine's LAN IP for direct LAN access. |

---

## Demo profiles (`config/*.ini`)

Every `.ini` directly inside the config directory shows up in the header's **Config**
dropdown. A profile declares which maps and which policies the demo offers.
[`config/example.ini`](config/example.ini) is a working starting point — copy it and edit:

```ini
[demo.maps]
map_0 = resources/drive/binaries/training/map_000000.bin

[policies.pretrained]
name = Pretrained
config = config/ocean/drive.ini
model = resources/drive/model_puffer_drive_003815.pt
```

- `[demo.maps]` — `<label> = <path to map binary>`. Relative paths are resolved against the
  config directory and its parents first, then against `DRIVE_BINARIES_DATA_ROOT`, so the
  same profile works with either the bundled resources or an external binaries folder.
- `[policies.<key>]` — one section per selectable policy. `model` is a `.pt` checkpoint;
  `config` is the drive ini describing the architecture that checkpoint was trained with
  (`[policy]`/`[rnn]` sizes, `policy_name`, and the `[env]` block, notably `dynamics_model`).
  A mismatch here surfaces in the UI as a red *"Failed to load"* message under the policy
  dropdown, and the demo falls back to a random policy.
- `[demo.ui]` and `[demo.features]` live in [`config/demo.ini`](config/demo.ini), which is
  read as a base layer under every profile — put shared colours and feature flags there.

Profiles other than `demo.ini`, `default.ini`, and `example.ini` are gitignored, so your own
`config/my_demo.ini` (pointing at your own checkpoints) stays local.

With no profile selected, the header falls back to a **Split** + **Map ID** selector that
walks `DRIVE_BINARIES_DATA_ROOT` directly.

---

## Using the demo

- **Header** — pick a Config profile, a Map (or split + map id), and a Policy, then hit
  **Load**. The second policy dropdown drives the ghost environment. **Reset** restarts the
  whole app (fresh Python process, no C rebuild).
- **Toolbar** — `Pan`, `Select`, `Move`, `Goals`, `Agent` (add a controlled agent), `Static`
  (add a parked vehicle). `Both` applies edits to the primary and ghost environment at once.
- **Timeline** — scrub, play/pause, and loop the 91-step rollout.
- **Scenarios** — the export dialog in the header writes the whole edited scene (map, policy,
  every edit, view flags) to `scenarios/<name>.json`. Exported scenes reappear in the Map
  dropdown marked with a ★ and restore losslessly. Checkpoint paths are stored relative to
  the repository root, so scenario files can be shared between machines.

The scenarios shipped in [`scenarios/`](scenarios/) reference the `testing` split — they need
a `DRIVE_BINARIES_DATA_ROOT` whose `testing/` directory is populated.

---

## Remote access

The demo serves the frontend on port `3000` and the backend on port `8000`.

### Over an SSH tunnel (works from any network)

Leave `HOST_IP` at its default (`localhost`) on the server and forward both ports. Add an
entry like this to your **local** `~/.ssh/config`, substituting your own hosts and usernames
(the `ProxyJump` line is only needed if the server sits behind a login/bastion host):

```
Host demo-host-fwd
    HostName <server-hostname-or-ip>
    User <your-username>
    ProxyJump <login-host>          # omit if the server is directly reachable
    LocalForward 3000 localhost:3000
    LocalForward 8000 localhost:8000
    ExitOnForwardFailure yes
```

Open the tunnel and keep the terminal running:

```bash
ssh demo-host-fwd
```

Then visit <http://localhost:3000>.

### Directly on the LAN

If your machine can reach the server directly, skip the tunnel and start the demo with the
server's IP so the browser can find the backend:

```bash
HOST_IP=<server-ip> ./run.sh
```

Then visit `http://<server-ip>:3000`.

---

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| *"No maps found in .../training"* | `DRIVE_BINARIES_DATA_ROOT` unset or pointing at a directory without `training/`, `validation/`, `testing/` subdirectories. |
| *"Failed to load: …"* under the policy dropdown | Checkpoint and `config` ini disagree — wrong `hidden_size`, `policy_name`, or a `dynamics_model` whose observation size differs from the one the checkpoint was trained with. The demo keeps running with a random policy. |
| Agents behave oddly, or new env options seem ignored | Stale C extension. Rebuild: `python setup.py build_ext --inplace --force`. |
| `run.sh` reports conflicting Reflex instances | A previous run is still holding ports 3000/8000. Answer `y` to let the script kill them. |
| Blank page / frontend cannot reach the backend | `HOST_IP` does not match the address the browser uses. Use the tunnel (default `localhost`) or set `HOST_IP` to the server's LAN IP. |

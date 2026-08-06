# DMScreen

DMScreen is a PySide6 desktop application for running a digital tabletop with separate Dungeon Master and Player displays. The DM window provides scene, layer, media, map, and measurement controls while the Player window shows the selected scene and synchronized view.

## Features

- Separate DM and Player windows
- Multiple scenes with tabs, names, caching, and close/clear workflows
- Portable `.dms` project archives with embedded media and schema migration
- Scene-specific Player zoom and pan settings
- DM tools for Player Pan, Ping, Ruler, and Shape overlays
- Grid, background, image, animation, video, drawing, and mask layers
- Animated media rendered in worker threads to keep the UI responsive
- Player view synchronization and scene indicator in the DM tab bar
- Frame settings, layer editing, visibility controls, and performance statistics
- Open, New, Save, Save As, Save All Scenes, and Clear All Scenes workflows

## Requirements

- Windows, macOS, or Linux
- Python 3.10 or newer
- A Qt-compatible desktop environment

Runtime dependencies are listed in `requirements.txt`:

- PySide6
- NumPy
- OpenCV headless

## Setup

Create and activate a virtual environment, then install the dependencies.

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks script activation for the current session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run

Start the application from the repository root:

```powershell
python main.py
```

On macOS or Linux, use the activated environment and run:

```bash
python main.py
```

The DM window opens first. The Player window can be shown from the Player menu or the Player controls.

## Tests

The test suite uses Qt's offscreen platform, so it can run without opening application windows.

### Windows PowerShell

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python run_tests.py
```

### macOS or Linux

```bash
QT_QPA_PLATFORM=offscreen python run_tests.py
```

The suite covers rendering and media behavior, layer editing, project archives and migration, scene/player view state, synchronized tools, and Qt widgets.

## Project Files

DMScreen projects use the `.dms` extension. A project archive contains the scene manifest, frame settings, layer data, Player view configuration, and embedded media assets. Projects are versioned and migrated when an older archive is opened.

Scene caches are stored in the platform-specific application data directory and are removed when scenes are closed or the application exits.

## Controls

- **Pan** moves the DM canvas.
- **Player Pan** moves the Player viewport. Ping, Ruler, and Shape are available when DM and Player are on the same scene.
- **Ping** places a temporary marker on both displays.
- **Ruler** measures between two points and snaps to grid cell centers when available.
- **Shape** previews circle, square, line, and cone areas with grid-aware selection.
- Layer visibility and Player visibility are controlled from the layer panel.

## Repository Layout

- `main.py` - application entry point
- `ui/controllers/dm.py` - DM/Player orchestration and scene lifecycle
- `ui/views/` - Qt widgets and display controls
- `media/` - media types and render helpers
- `project_io.py` - `.dms` archive persistence and migrations
- `scenes.py` - scene model and scene-owned Player view state
- `tests/` - automated test suite

## License

No license is currently specified for this repository.

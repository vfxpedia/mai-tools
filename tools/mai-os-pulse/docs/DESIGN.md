# mai-os Pulse · Design and fit review
2026-10-13 KST · Version 0.1.2

Purpose: local workstation observability for AI development, model training/inference, robotics simulation, data preparation and long-running services. AI-WS01 is the intended deployment host; the actual hostname is detected, not fabricated.

User principles interpreted from this conversation: one consistent UI across Windows and Ubuntu; modular OS adapters; observable quality and repeatable verification; useful evidence before intervention; low interference. This is an interpretation, not a claim to have read an authoritative mai-os manifesto.

## Choice
Rainmeter + HWiNFO: mature Windows skinning, but no Linux runtime. A browser dashboard: portable UI, but browser lifecycle and additional runtime for a local side panel. Selected: native Qt/PySide6 desktop UI with a background collector and OS sensor adapters. Qt Essentials only; no browser engine, cloud service, TCP listener, CUDA context, process termination, working-set trimming, driver changes or scheduler changes.

## Data and workflow fit
- Per-GPU UUID and PCI identity, compute utilization, allocated VRAM, temperature and power. Each 16GB GPU is evaluated separately; aggregate memory is not assumed to be a single allocation pool.
- CPU average plus maximum logical-processor load, expandable logical-processor grid. Logical processors are not presented as independent physical cores.
- RAM used/available plus process RSS and time-based growth. Process CPU uses 100%=one logical processor; overall CPU uses 100%=all logical processors.
- Local volume free space and separately labelled disk/block-device I/O. Do not guess volume-to-SSD mappings or RAID relationships.
- Active network interfaces separated, to distinguish NAS traffic from other network activity. Interface counters are traffic, not network capacity, latency or NAS health.
- Process diagnostic view: RSS, CPU, age, parent PID, status, observed RSS growth over up to 60 seconds. High usage and long age are evidence, not proof of waste or a leak. Manual system task-manager launch is provided.

## Sensor boundaries
GPU readings use NVIDIA NVML. No driver/model guarantee is claimed before deployment; unsupported functions are individually unavailable. Per-process GPU memory is omitted due to WDDM limitations. Initialization is retried if the driver is unavailable.
Windows CPU thermal/power and SSD thermal data require externally exported HWiNFO Gadget readings. Registry adapter is read-only; mapped identities use sensor/label names instead of index only, with ambiguity refusal and a 15-second registry last-write freshness guard. Exported sensors are listed in details; CPU temperature and package power have explicit mapping controls. License terms are for the user to determine from the official HWiNFO license; HWiNFO is not bundled or installed.
Linux temperature readings use psutil/hwmon, including exposed NVMe temperatures. CPU power is not collected by a privileged MSR/energy driver in this version and usually remains unavailable. Sensors that are not exposed stay unavailable.
CPU effective clocks, Windows commit charge, SMART lifespan/health and GPU throttle reason are deferred, not substituted with misleading proxy values.

## Lifecycle and cost
Samples every 2/5/10 seconds; capacities, sensors and process diagnostics every 10 seconds. Hidden tray mode uses 10-second sampling. Histories are bounded to 60 samples and seven RSS samples per process. UI uses a worker thread; pause and full exit are available. Default is a normal window, without topmost, hooks or reserved desktop work area. A narrow screen-relative right panel is positioned on the chosen monitor; Wayland may override positioning. User can resize/move it normally.
Login startup is current-user Windows Run entry or Linux Desktop Entry. Multiboot shares code and concepts, not live state or a single executable. macOS, mobile and other OS are not validated/supported release targets.

## Validation and limitations
Unit/integration checks exercise missing values, counter resets, per-GPU memory, single-thread saturation, removed/ambiguous sensors, absent self-process permissions, process growth and Qt rendering. Linux/container live collection and offscreen UI verified. Windows build/install, AI-WS01 sensors, RTX 5080 NVML support in its installed driver, Ubuntu desktop integration and actual workload overhead remain hardware/deployment verification tasks.

## v0.1.1 resilience amendment
Optional NVML, volume, network, disk I/O, sensor, process and physical-core/swap adapters now run as bounded daemon jobs with independent caches. CPU/RAM snapshots do not wait for them. Stale/blocked/failed adapter values are unavailable; errors are shown and bounded local error logs are enabled. No socket server, driver management or process optimization is added.

## 0.1.2 process-scan amendment
Actual Windows diagnosis identified the old scan timeout. Process scans are now on-demand, isolated in a child without Qt imports, bounded to 5s, and stopped on app shutdown. Parent/status metadata is omitted; core metrics remain independent. Historical sections describe earlier designs and are superseded by this amendment.

# Mission Template

This directory is a starting point for new mission packages. Copy it, rename it,
and implement the adapter to add a new mission to the platform.

## How to Use

```bash
# 1. Copy the template
cp -r mav_gss_lib/missions/template mav_gss_lib/missions/<your_mission>

# 2. Activate it in config
#    Set general.mission: <your_mission> in mav_gss_lib/gss.yml

# 3. Update mission metadata
#    Edit mav_gss_lib/missions/<your_mission>/mission.example.yml

# 4. Implement the adapter
#    Edit mav_gss_lib/missions/<your_mission>/adapter.py

# 5. (Optional) Add a command schema
cp mav_gss_lib/missions/<your_mission>/commands.example.yml \
   mav_gss_lib/missions/<your_mission>/commands.yml
# then populate commands.yml with real commands
# add commands.yml to .gitignore if security-sensitive

# 6. (Optional) Add a frontend TX builder
#    Create mav_gss_lib/web/src/plugins/<your_mission>/TxBuilder.tsx
#    The platform auto-discovers it by convention — no registration needed
```

## Files in This Template

| File | Purpose |
|------|---------|
| `__init__.py` | Package entry: `ADAPTER_API_VERSION`, `ADAPTER_CLASS`, `init_mission` |
| `adapter.py` | Stub `TemplateMissionAdapter` — every method has a docstring |
| `mission.example.yml` | Minimal public-safe metadata to track in version control |
| `commands.example.yml` | Minimal command schema example — copy to `commands.yml` |

## Key Principle

**The platform owns mechanics. The mission owns semantics.**

The platform handles transport, queue execution, logging, and generic UI rendering.
Your mission package tells the platform:
- How to parse received bytes into meaningful data
- How to build transmit bytes from operator input
- How to present data and commands to operators

The platform never reads `mission_data` directly — it passes it through to your
rendering and logging methods. You control all mission-specific interpretation.

## Discover More

- `docs/adding-a-mission.md` — full mission authoring guide with adapter protocol
  reference, rendering contracts, TX flow, and testing guide
- `tests/echo_mission.py` — minimal working non-MAVERIC adapter (passes all validation)
- `mav_gss_lib/mission_adapter.py` — `MissionAdapter` Protocol definition

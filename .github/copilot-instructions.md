# Climate React Custom Integration for Home Assistant

## Project Overview

This is a **Home Assistant custom integration** called `climate_react` that replicates Sensibo's Climate React functionality with extended features for humidity control and advanced automation. The integration monitors temperature and humidity sensors and automatically adjusts HVAC system settings (mode, fan, swing) based on configurable thresholds with reliability safeguards.

**Current Status**: ✅ **Feature Complete** - Ready for testing and distribution via HACS

**Key Differentiators:**
- No Node-RED needed - all automation in Home Assistant
- Capability-aware entity creation (only shows supported modes)
- Manual override detection prevents automation conflicts
- Minimum runtime prevents equipment wear
- Works with built-in climate entity sensors or external sensors
- Multi-AC support - run independent instances per climate entity

## Architecture

### Component Structure
```
custom_components/climate_react/
├── __init__.py          # Integration initialization, domain setup, service registration
├── manifest.json        # Integration metadata, dependencies
├── const.py             # Constants for config keys, defaults, modes
├── climate_react.py     # Core automation logic (sensor monitoring → HVAC control)
├── config_flow.py       # UI setup flow with flexible sensor configuration
├── services.yaml        # Custom service definitions
├── strings.json         # UI labels and descriptions (config flow)
├── translations/en.json # Localization strings
├── switch.py            # Enable/disable automation switch entity
├── sensor.py            # Enhanced status sensor + temperature/humidity mirrors
├── number.py            # Threshold & configuration controls (min/max temp, delays, runtime)
├── select.py            # Dynamic mode/fan/swing selection (filtered by climate capabilities)
└── README.md            # User documentation
```

### Data Flow
1. Subscribe to temperature/humidity sensor state changes (or climate entity attributes)
2. Compare current reading against user-configured thresholds
3. Check if minimum runtime elapsed since last mode change
4. Retrieve target HVAC mode/fan/swing from config (only if climate supports it)
5. Call climate domain service with mode settings and optional target temperature
6. Apply configurable delay between sequential service calls
7. Track mode change timestamp for minimum runtime enforcement
8. Update status sensor with current state (heating/cooling/idle/etc)

### Key Integration Points
- **Home Assistant Climate Domain**: Controls target climate entity (e.g., `climate.bedroom`)
- **Sensor Domain**: Reads from external temperature/humidity sensors OR climate entity's attributes
- **Number Domain**: Provides UI controls for thresholds, target temps, delays, minimum runtime
- **Select Domain**: Provides mode/fan/swing configuration with dynamic options from climate
- **Switch Domain**: Enable/disable toggle with manual override detection
- **Config Flow**: Flexible UI-driven setup (optional external sensors)
- **Device Interface**: All entities grouped under single device per climate entity
- **Event System**: State change listeners (no polling for efficiency)

## Implemented Features

### Core Functionality
✅ Temperature threshold-based HVAC control (heating/cooling)
✅ Optional humidity control (dehumidification/humidification)
✅ Humidifier entity support (turn on/off based on humidity)
✅ Dynamic select entities (only show supported climate capabilities)
✅ Multi-AC support (separate config entries per climate entity)

### Sensor Options
✅ External temperature sensor (optional)
✅ External humidity sensor (optional)
✅ Built-in climate entity temperature (fallback)
✅ Built-in climate entity humidity (fallback)

### Advanced Features
✅ Configurable delays between sequential commands (0-5000ms)
✅ Configurable minimum runtime between mode changes (0-120 minutes)
✅ Manual override detection (disables automation gracefully)
✅ Climate entity limit synchronization (clamps thresholds)
✅ Late-loading climate entity support

### Entity Types Created
✅ **Switch**: Enable/disable automation
✅ **Sensor**: Enhanced status sensor (state + current readings + thresholds)
✅ **Number** (7 core + optional):
   - Min/Max temperature thresholds
   - Target temperatures (low temp, high temp, high humidity)
   - Delay between commands (milliseconds)
   - Minimum run time (minutes)
   - Min/Max humidity thresholds (only if humidity enabled + humidifier configured for min)
✅ **Select** (12 when all conditions met):
   - HVAC modes (low temp, high temp, high humidity) - filtered options
   - Fan modes (low temp, high temp, high humidity)
   - Swing modes (low temp, high temp, high humidity)
   - Horizontal swing modes (low temp, high temp, high humidity)

### Home Assistant Patterns

#### Configuration Flow Architecture
- **Config Flow** (`config_flow.py`): 
  - Climate entity selection (required)
  - Use external temp sensor checkbox (optional - default: use climate entity's built-in)
  - Temperature sensor selection (only if external checked)
  - Enable humidity checkbox (optional - default: disabled)
  - Use external humidity sensor checkbox (only if humidity enabled)
  - Humidity sensor selection (only if external humidity checked)
  - Humidifier entity selection (optional)
  
- **Options Flow**: 
  - Same entity selections as config flow (allow changing after setup)
  - All other parameters controlled via number/select entities

- **Number Entities**: Provide runtime configuration (thresholds, targets, delays)
- **Select Entities**: Provide mode configuration (only for supported capabilities)
- **Switch**: Enable/disable with manual override tracking
- **Sensor**: Status with rich attributes
- **Device Grouping**: All entities under single device per climate entity
- **Entity Naming**: Uses `has_entity_name = True` for proper hierarchy

#### Device Architecture
All entities belong to one device with:
- **Identifiers**: `(DOMAIN, entry.entry_id)` - ensures uniqueness per climate entity
- **Name**: "Climate React - [climate_entity_name]"
- **Model**: "Climate Automation Controller"
- **Manufacturer**: "Climate React"
- **SW Version**: "0.1.0"

#### Manual Override Detection
- Tracks last HVAC mode set by automation (`_last_set_hvac_mode`)
- Listens to climate entity state changes
- Compares expected mode vs actual mode
- If mismatch detected: 
  - Disables automation (`_enabled = False`)
  - Logs warning with clear context
  - User must manually re-enable switch

#### Minimum Runtime Logic
- Tracks timestamp of last mode change (`_last_mode_change_time`)
- Threshold checks verify min runtime elapsed before allowing mode change
- If min runtime not elapsed, threshold is ignored (not mode changed)
- Example: 5-min runtime + temp oscillates = no rapid cycling

#### Status Sensor States
- "disabled" - automation disabled via switch
- "waiting" - no sensor reading yet
- "heating" - temp below min threshold
- "cooling" - temp above max threshold  
- "dehumidifying" - humidity above max threshold
- "humidifying" - humidity below min threshold
- "idle" - within comfortable range

#### Status Sensor Attributes
- temperature (current reading if available)
- temperature_min / temperature_max (configured thresholds)
- humidity (current reading if available)
- humidity_min / humidity_max (configured thresholds)
- mode_low_temp / mode_high_temp / mode_high_humidity (configured modes)
- climate_entity (the target AC being controlled)

## Common Implementation Patterns

### Threshold Comparison Logic
```python
# In _async_handle_temperature_threshold()
if temperature < min_temp:
    mode = config[CONF_MODE_LOW_TEMP]  # e.g., "heat"
    await self._async_set_climate(mode, fan_mode, swing_mode, ...)
elif temperature > max_temp:
    mode = config[CONF_MODE_HIGH_TEMP]  # e.g., "cool"
    await self._async_set_climate(mode, fan_mode, swing_mode, ...)
```

### Service Call Pattern
```python
await self.hass.services.async_call(
    "climate", "set_hvac_mode",
    {"entity_id": self.climate_entity, "hvac_mode": mode},
    blocking=True,
)
```

### Dynamic Mode Filtering
```python
# Select entity only shows modes climate actually supports
_allowed_options = ["heat", "fan_only", "off"]  # for low temp
# In _refresh_options():
supported = climate_state.attributes.get("hvac_modes")
options = [opt for opt in supported if opt in self._allowed_options]
```

### State Change Listener Pattern
```python
async_track_state_change_event(
    hass, [entity_id], callback_function
)
# vs polling - much more efficient
```

## Testing Checklist

- [ ] Config flow accepts climate entity without external sensors
- [ ] Config flow validates entities exist
- [ ] Select entities show only supported modes from climate
- [ ] Number entities update config and controller
- [ ] Temperature threshold triggers mode changes
- [ ] Humidity threshold triggers humidifier
- [ ] Manual override detected and logged
- [ ] Minimum runtime prevents rapid mode changes
- [ ] Status sensor shows correct state with attributes
- [ ] Switch enables/disables automation
- [ ] Multi-AC setup works independently
- [ ] Climate entity built-in sensors work (no external sensors)
- [ ] External sensors work when enabled
- [ ] Delays apply between service calls

### Quick Setup
Users can add integration directly from:
https://my.home-assistant.io/redirect/config_flow_start?domain=climate_react

## Reference Files

- **Integration README**: [../../ha-climate-react/README.md](../../ha-climate-react/README.md) - Detailed feature docs
- **HA Integration Docs**: https://developers.home-assistant.io/docs/creating_integration_manifest
- **Config Flow Guide**: https://developers.home-assistant.io/docs/config_entries_config_flow_handler

## Common Pitfalls to Avoid

- Don't use `configuration.yaml` for setup (this is UI-configured integration)
- Don't poll sensors continuously (use `async_track_state_change_event`)
- Don't forget to unsubscribe listeners in `async_unload_entry`
- Don't hardcode entity IDs (always use config/options values)
- Always update both config entry options AND controller state when number/select entities change
- Ensure all entities share identical `device_info` dict
- Use `has_entity_name = True` for all entities
- Config/Options flow only handles entity selection
- All other parameters via number/select entities
- Select options must be filtered to what climate actually supports

## Architecture

### Component Structure
```
custom_components/climate_react/
├── __init__.py          # Integration initialization, domain setup, service registration
├── manifest.json        # Integration metadata, dependencies
├── const.py             # Constants for config keys, thresholds, modes
├── climate_react.py     # Core automation logic (sensor monitoring → HVAC control)
├── config_flow.py       # Initial setup UI flow with validation
├── services.yaml        # Custom service definitions
├── strings.json         # UI labels and descriptions
├── translations/en.json # Localization strings
├── switch.py            # Enable/disable switch entity
├── sensor.py            # Status, temperature, and humidity sensors
├── number.py            # Threshold control entities (min/max temp/humidity)
├── select.py            # Mode/fan/swing selection entities
└── README.md            # User documentation
```

### Data Flow
1. Monitor temperature/humidity sensor entities → 2. Compare against user-configured thresholds → 3. Trigger appropriate HVAC mode/fan/swing changes → 4. Respect enable/disable switch state → 5. Update device sensors with current status

### Key Integration Points
- **Home Assistant Climate Domain**: Controls target climate entity (e.g., `climate.bedroom`)
- **Sensor Domain**: Reads from external temperature/humidity sensors, exposes status sensors
- **Number Domain**: Provides threshold controls (min/max temp, humidity)
- **Select Domain**: Provides mode/fan/swing configuration entities
- **Config Flow**: UI-driven setup (not YAML-based configuration)
- **Device Interface**: All entities grouped under single device for unified control
- **Services**: Custom services for runtime control (enable/disable, update thresholds)

## Home Assistant Specific Patterns

### Configuration Flow Architecture
- **Config Flow** (`config_flow.py`): Initial setup - prompts for climate entity, temperature sensor, humidity sensor only
- **Options Flow** (`config_flow.py`): Post-setup editing - allows changing climate entity and sensors only
- **Number Entities**: Provide UI controls for thresholds (min/max temp/humidity)
- **Select Entities**: Provide UI controls for modes (HVAC, fan, swing) per condition
- **Switch**: Enable/disable toggle with extra state attributes
- **Sensor**: Status sensor (heating/cooling/idle) + mirror sensors for temp/humidity
- All entities share common device_info to group under single device
- All entities use `has_entity_name = True` for proper naming
- All parameters except entities are configured through the device's number/select entities

### Device Architecture
All entities belong to a single device with:
- **Identifiers**: `(DOMAIN, entry.entry_id)`
- **Name**: "Climate React - [climate_entity_name]"
- **Model**: "Climate Automation Controller"
- **Manufacturer**: "Climate React"
- Use `switch.py` for enable/disable toggles (not binary_sensor)
- Each automation aspect (fan, swing, humidity) gets its own module
- All entities must reference the parent climate entity

### Manifest Requirements
- Specify `config_flow: true` for UI-based setup
- Include `requirements: []` even if empty (no external Python packages)
- Set `iot_class: local_polling` for sensor monitoring
- VAdd `sensor.py` for status and reading displays
7. Add `number.py` for threshold controls
8. Add `select.py` for mode/fan/swing configuration
9. Add `services.yaml` and service handlers in `__init__.py`
10. Update `PLATFORMS` in `__init__.py` to include all entity type

### Initial Implementation Order
1. Create folder structure in HA config: `config/custom_components/climate_react/`
2. Implement `manifest.json` and `const.py` first (foundation)
3. Build `config_flow.py` to enable UI setup
4. Implement `climate_react.py` core logic (temperature monitoring → mode changes)
5. Add `switch.py` for enable/disable control
6. Extend with `fan.py`, `swing.py`, `humidity.py` features
7. Implement `options_flow.py` for configuration editing
8. Add `services.yaml` and service handlers

### Testing Approach
- Test incrementally - start with basic temperature → mode switching
- Use Home Assistant's built-in template sensors for testing thresholds
- Check `home-assistant.log` for debug messages (use `_LOGGER.debug()`)
- Create test automations that set sensor values programmatically

### Code Conventions
- Use `async def` for all integration entry points (`async_setup`, `async_setup_entry`)
- Prefix private methods with `_` (e.g., `_handle_temperature_change`)
- Store user config in `entry.data` (immutable) and `entry.options` (editable)
- Use `hass.data[DOMAIN]` for runtime state tracking
- Import constants from `const.py` (never hardcode strings like "climate_entity")

## Specific Implementation Guidance

### Threshold Comparison Logic
Monitor sensor state changes and compare against min/max thresholds:
```python
# Example pattern from climate_react.py
if temp < self.config['min_temp_threshold']:
    await self.set_hvac_mode(self.config['mode_low_temp'])  # e.g., "heat"
elif temp > self.config['max_temp_threshold']:
    await self.set_hvac_mode(self.config['mode_high_temp'])  # e.g., "cool"
```

### Service Call Pattern
Use `hass.services.async_call()` to control climate entity:
```python
await self.hass.services.async_call(
    "climate", "set_hvac_mode",
    {"entity_id": self.climate_entity, "hvac_mode": mode}
)
```

### Entity Implementation Patterns

#### Number Entities
```python
async def async_set_native_value(self, value: float) -> None:
    """Update threshold - must update both config entry options and controller."""
    new_options = {**self._entry.options}
    new_options[self._config_key] = value
    selfpoll sensors continuously (use state change listeners: `async_track_state_change_event`)
- Don't forget to unsubscribe listeners in `async_will_remove_from_hass` for sensor entities
- Don't forget to unsubscribe listeners in `async_unload_entry` for the controller
- Don't hardcode entity IDs (always use config/options values)
- Always update both config entry options AND controller state when number/select entities change
- Ensure all entities share identical `device_info` dict for proper device grouping
- Use `has_entity_name = True` for all entities to enable proper naming hierarchy
#### Select Entities
```python
async def async_select_option(self, option: str) -> None:
    """Change mode/fan/swing - updates config entry options."""
    new_options = {**self._entry.options}
    new_options[self._config_key] = option
    self.hass.config_entries.async_update_entry(self._entry, options=new_options)
```

#### Sensor Entities
- Use `async_track_state_change_event` to mirror source sensor values
- Status sensor derives state from controller's current readings vs thresholds
- Set `should_poll = False` and update via event callbacks

## Reference Files

- **Blueprint**: [copilot-instructions.md](copilot-instructions.md) - Complete file-by-file specifications
- **HA Integration Docs**: https://developers.home-assistant.io/docs/creating_integration_manifest
- **Config Flow Guide**: https://developers.home-assistant.io/docs/config_entries_config_flow_handler

## Common Pitfalls to Avoid

- Don't use `configuration.yaml` for setup (this is a UI-configured integration)
- Don't poll sensors continuously (use state change listeners: `async_track_state_change_event`)
- Don't forget to unsubscribe listeners in `async_will_remove_from_hass` for sensor entities
- Don't forget to unsubscribe listeners in `async_unload_entry` for the controller
- Don't hardcode entity IDs (always use config/options values)
- Always update both config entry options AND controller state when number/select entities change
- Ensure all entities share identical `device_info` dict for proper device grouping
- Use `has_entity_name = True` for all entities to enable proper naming hierarchy
- Config/Options flow only handles entity selection - all other parameters via number/select entities
- Number/select entities automatically update config entry options when changed

# Climate React - Home Assistant Custom Integration

[![GitHub release](https://img.shields.io/github/release/ttlucian/ha-climate-react.svg)](https://github.com/ttlucian/ha-climate-react/releases)
[![License](https://img.shields.io/github/license/ttlucian/ha-climate-react.svg)](LICENSE)

A Home Assistant custom integration that replicates Sensibo's Climate React functionality with extended support for humidity control. Automatically adjusts your HVAC system based on temperature and humidity sensor readings.

## Features

- 🌡️ **Temperature-Based Control**: Automatically switch between heating and cooling modes based on configurable temperature thresholds
- 💧 **Humidity Control**: Trigger dehumidify mode when humidity exceeds thresholds
- 🎛️ **Fan & Swing Automation**: Configure different fan speeds and swing modes for each condition
- 🔄 **Dynamic Thresholds**: Update thresholds on-the-fly via services or the UI
- 🎯 **UI Configuration**: Easy setup through Home Assistant's UI (no YAML required)
- 🔌 **Enable/Disable Switch**: Control automation with a simple switch entity
- 📊 **State Monitoring**: Real-time sensor monitoring with state change listeners

## Installation

### HACS

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/ttlucian/ha-climate-react`
6. Select "Integration" as the category
7. Click "Add"
8. Search for "Climate React" in HACS
9. Click "Download"
10. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/climate_react` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

### Initial Setup

1. Go to **Configuration** → **Integrations**
2. Click **+ Add Integration**
3. Search for **Climate React**
4. Follow the setup wizard:
   - Select your climate entity (e.g., `climate.bedroom`)
   - Choose temperature sensor (required)
   - Choose humidity sensor (optional)
   - Set temperature thresholds (min/max)
   - Set humidity thresholds (optional)
   - Configure HVAC modes for different conditions
   - Set fan and swing modes (optional)
   - Enable or disable the automation

### Adjusting Settings

After initial setup, you can modify thresholds and modes:

1. Go to **Configuration** → **Integrations**
2. Find **Climate React**
3. Click **Configure**
4. Adjust your settings
5. Click **Submit**

## Usage

### Enable/Disable via Switch

A switch entity is created automatically: `switch.climate_react`

```yaml
# Example automation to disable during specific hours
automation:
  - alias: "Disable Climate React at Night"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.climate_react
```

### Services

#### Enable Climate React
```yaml
service: climate_react.enable
data:
  entity_id: climate.bedroom  # Optional, omit to enable all
```

#### Disable Climate React
```yaml
service: climate_react.disable
data:
  entity_id: climate.bedroom  # Optional, omit to disable all
```

#### Update Thresholds
```yaml
service: climate_react.update_thresholds
data:
  entity_id: climate.bedroom
  min_temp: 19.0
  max_temp: 25.0
  min_humidity: 30
  max_humidity: 65
```

## How It Works

1. **Temperature Monitoring**: The integration monitors your temperature sensor
   - Below minimum threshold → Activates heating mode
   - Above maximum threshold → Activates cooling mode
   - Within range → No action (or turn off based on configuration)

2. **Humidity Monitoring**: If humidity sensor is configured
   - Above maximum threshold → Activates dry/dehumidify mode

3. **Fan & Swing Control**: Automatically adjusts fan speed and swing direction based on the active condition

4. **Priority**: Humidity control takes precedence over temperature when both thresholds are exceeded

## Example Configuration

```yaml
# Temperature thresholds
Min Temperature: 18°C → HVAC Mode: heat, Fan: auto, Swing: off
Max Temperature: 26°C → HVAC Mode: cool, Fan: high, Swing: vertical

# Humidity thresholds (optional)
Max Humidity: 65% → HVAC Mode: dry, Fan: medium, Swing: horizontal
```

## Debugging

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.climate_react: debug
```

Check `home-assistant.log` for detailed information about threshold evaluations and HVAC commands.

## Troubleshooting

### Integration doesn't respond to sensor changes
- Verify sensors are updating properly
- Check that Climate React switch is enabled
- Review logs for errors
- Ensure climate entity supports the configured modes

### HVAC mode not changing
- Verify your climate entity supports the configured HVAC modes
- Check if climate entity is in a manual mode override
- Review service call errors in the logs

### Fan/Swing modes not working
- Ensure your climate entity supports fan and swing modes
- Check the available modes in Developer Tools → States
- Some climate entities may have different mode names

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Inspired by Sensibo's Climate React feature
- Built for the Home Assistant community

## Support

- [Report Issues](https://github.com/ttlucian/ha-climate-react/issues)
- [Feature Requests](https://github.com/ttlucian/ha-climate-react/issues)
- [Discussions](https://github.com/ttlucian/ha-climate-react/discussions)

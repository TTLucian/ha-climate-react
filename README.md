# Climate React - Home Assistant Custom Integration

<p align="center">
  <img src="https://img.shields.io/github/v/release/TTLucian/ha-climate-react?style=for-the-badge" />
  <img src="https://img.shields.io/github/license/TTLucian/ha-climate-react?style=for-the-badge" />
  <img src="https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge" />
  <img src="https://img.shields.io/github/actions/workflow/status/TTLucian/ha-climate-react/validate.yml?style=for-the-badge" />
</p>

A Home Assistant custom integration that automatically controls your HVAC system based on temperature and humidity thresholds. Inspired by Sensibo's Climate React feature with extended functionality.

## 🌟 Features

- **Automatic Temperature Control**: Switch between heating/cooling based on sensor readings
- **Humidity Management**: Automatic dehumidification and humidification with humidifier entity support
- **Flexible Sensor Input**: Use external sensors or climate entity's built-in temperature/humidity
- **Fan & Swing Automation**: Configure different settings for each condition (cold/hot/humid)
- **Display Light Control**: Optionally toggle the AC display light when automation starts/stops and around commands
- **Countdown Timer**: Built-in timer entity to auto-disable the automation after a set duration
- **Capability Matching**: Select entities only show modes/fans/swings your climate supports
- **Minimum Runtime Protection**: Configurable minimum time between mode changes (prevents rapid cycling)
- **Manual Override Detection**: Gracefully disables automation when user manually changes mode
- **Enhanced Status Sensor**: Shows current state, temperature, humidity, and thresholds
- **UI Configuration**: Easy setup through Home Assistant's interface
- **Dynamic Adjustments**: Update thresholds on-the-fly
- **Enable/Disable Control**: Simple switch to turn automation on/off
- **Multi-AC Support**: Run independent instances for multiple climate entities

## 📦 Installation

### Via HACS (Custom Repository)

1. Open HACS in Home Assistant
2. Go to **Integrations** → **⋮ (menu)** → **Custom repositories**
3. Add repository: `https://github.com/TTLucian/ha-climate-react`
4. Select category: **Integration**
5. Click **Add**
6. Go back to **Integrations**
7. Search for **Climate React**
8. Click **Install**
9. Restart Home Assistant

Or click here to add the repository directly:

[![Add Solar AC Controller to HACS](https://img.shields.io/badge/HACS-Add%20Solar%20AC%20Controller-blue?style=for-the-badge)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TTLucian&repository=ha-climate-react&category=integration)

[![Add Solar AC Controller Integration](https://img.shields.io/badge/Home%20Assistant-Add%20Integration-blue?style=for-the-badge&logo=homeassistant)](https://my.home-assistant.io/redirect/config_flow_start?domain=ha-climate-react)

### Manual Installation

1. Download the latest release from [GitHub](https://github.com/TTLucian/ha-climate-react/releases)
2. Extract to `config/custom_components/climate_react/`
3. Restart Home Assistant

See [Integration Documentation](custom_components/climate_react/README.md#installation) for detailed instructions.

## 📚 Documentation

Full documentation is available in the [integration README](custom_components/climate_react/README.md)

## 🚀 Quick Start

1. Install via HACS or manually
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Integrations**
4. Click **Create Integration** and search for **Climate React**
5. Step 1: choose your climate entity and toggle features (external temperature, humidity use, external humidity, light control)
6. Step 2: provide required entities for enabled features (temperature sensor when external temp is on, humidity sensor when external humidity is on, light entity when light control is on); humidifier remains optional
7. Finish and adjust thresholds/modes in the integration's device settings

## 💡 Example Use Cases

- **Bedroom**: Keep temperature between 18-26°C, heat at night, cool during day
- **Humidity Control**: Prevent mold - dehumidify above 60%, humidify below 30%
- **Office**: Maintain 20-25°C, adjust fan speed based on temperature
- **Energy Efficiency**: Use climate entity's temperature instead of extra sensors
- **Multi-Zone**: Set up separate instances for bedroom, living room, office, etc.

## ⚙️ Configuration

All configuration happens through Home Assistant UI:

**Setup (Config Flow):**

- Climate entity (required) plus toggles for external temperature, humidity use, external humidity, and light control
- Required selectors only for enabled features (external temperature sensor, external humidity sensor, light entity). Humidifier is optional.

**After Setup (Device Entities):**

- **Switch**: Climate React enable/disable and optional light control switch
- **Numbers**: Temperature/humidity thresholds, target temperatures, delays, minimum runtime, timer minutes
- **Selects**: HVAC modes, fan modes, swing modes, light behavior per condition
- **Sensors**: Status, current readings, timer countdown

## 🛠️ Features Detail

### Temperature Control

- **Min Temperature**: Temperature at which heating triggers
- **Max Temperature**: Temperature at which cooling triggers
- **Target Temperatures**: Set specific target temp for heating/cooling
- **Minimum Runtime**: Prevent mode changes within X minutes (default 5)

### Humidity Control (Optional)

- **Min Humidity**: Humidity level to trigger humidification
- **Max Humidity**: Humidity level to trigger dehumidification
- Requires humidity sensor and/or humidifier entity

### Mode Configuration

- **Low Temperature**: Heating mode (heat, fan_only, off)
- **High Temperature**: Cooling mode (cool, fan_only, off)
- **High Humidity**: Dehumidify mode (dry, fan_only, off)
- Only shows modes your climate entity supports

### Safety Features

- **Manual Override Detection**: Detects manual mode changes and disables automation
- **Minimum Runtime**: Prevents rapid mode switching
- **Capability Matching**: Only creates entities for supported features
- **Graceful Degradation**: Works without external sensors

## 📊 Development

This project follows Home Assistant's integration development guidelines:

- Config Flow for UI-based setup
- Options Flow for post-setup configuration
- Event-driven (no polling for efficiency)
- Proper device grouping
- State change listeners for sensor monitoring

See [.github/copilot-instructions.md](.github/copilot-instructions.md) for detailed development guidelines.

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Open a pull request

## 📞 Support

- [Issues](https://github.com/TTLucian/ha-climate-react/issues) - Bug reports and feature requests
- [Discussions](https://github.com/TTLucian/ha-climate-react/discussions) - Questions and ideas

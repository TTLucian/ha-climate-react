# Climate React Custom Integration for Home Assistant

This file contains complete instructions for building a **Home Assistant custom integration** called `climate_react`.  
It replicates Sensibo's *Climate React* functionality and extends it with **Humidity React**, **Options Flow**, and **Reconfiguration Flow**.  
Use this file in **VS Code with GitHub Copilot** — Copilot will generate the code for each file based on these descriptions.

---

## 📂 Project Structure

Create the following folder inside your Home Assistant `config/custom_components` directory:

custom_components/
└── climate_react/
├── init.py
├── manifest.json
├── const.py
├── climate_react.py
├── services.yaml
├── config_flow.py
├── options_flow.py
├── strings.json
├── translations/
│   └── en.json
├── switch.py
├── fan.py
├── swing.py
├── humidity.py
└── README.md

Code

---

## 📝 File Responsibilities

- **`__init__.py`**  
  Initialize the integration, set up domain, and load configuration.

- **`manifest.json`**  
  Metadata: domain name, version, documentation link, requirements, codeowners.

- **`const.py`**  
  Define constants for configuration keys (climate entity, sensors, thresholds, modes, etc.).

- **`climate_react.py`**  
  Core logic: monitor temperature and humidity sensors, trigger HVAC, fan, and swing changes.

- **`services.yaml`**  
  Define custom services (enable/disable Climate React, update thresholds dynamically).

- **`config_flow.py`**  
  Handle initial setup via Home Assistant UI. Prompt user for climate entity, sensors, thresholds, and enable switch.

- **`options_flow.py`**  
  Allow users to adjust thresholds, modes, fan, swing, and humidity settings after setup.

- **`strings.json`**  
  Define UI labels and descriptions for config and options flows.

- **`translations/en.json`**  
  Provide English translations for strings. Additional languages can be added later.

- **`switch.py`**  
  Implement enable/disable switch entity for Climate React.

- **`fan.py`**  
  Handle fan mode adjustments when thresholds are crossed.

- **`swing.py`**  
  Handle swing mode adjustments.

- **`humidity.py`**  
  Add Humidity React logic: monitor humidity sensor and trigger dehumidify mode.

- **`README.md`**  
  User-facing documentation: installation, configuration, usage, troubleshooting.

---

## ⚙️ Configuration

Users configure the integration in `configuration.yaml` or via the UI.  
Required inputs:
- Climate entity (e.g., `climate.bedroom`)  
- Temperature sensor  
- Humidity sensor (optional)  
- Min/max temperature thresholds  
- Min/max humidity thresholds  
- Modes for low/high temperature  
- Mode for high humidity (e.g., "dry")  
- Enable switch  
- Fan and swing settings for each condition  

---

## 🔄 Configuration Flow

- **Config Flow**  
  Runs when integration is first added. Prompts user for climate entity, sensors, thresholds, and enable switch.

- **Options Flow**  
  Runs when user edits integration. Allows updating thresholds, modes, fan/swing settings, and humidity options.

- **Reconfiguration Flow**  
  Supports editing configuration after initial setup without removing/re-adding the integration.

---

## 📜 strings.json

Defines UI labels and descriptions for config and options flows.  
Include fields for climate entity, sensors, thresholds, modes, fan, swing, and humidity options.

---

## 🌐 translations/en.json

Provides English translations for all strings defined in `strings.json`.  
Additional languages can be added by creating more JSON files in the `translations/` folder (e.g., `de.json`, `fr.json`).

---

## 🚀 Setup Instructions

1. Copy the `climate_react` folder into `config/custom_components/`.  
2. Restart Home Assistant.  
3. Add the integration via the UI (Configuration → Integrations → Add Integration → Climate React).  
4. Complete the **Config Flow** to set up climate entity, sensors, and thresholds.  
5. Use the **Options Flow** to adjust thresholds and modes later.  
6. Test by adjusting sensor values and observing climate entity changes.  
7. Check `home-assistant.log` for debug messages.  

---

## 🧩 Enhancements

- **Humidity React:** Monitor humidity sensors and trigger dehumidify mode.  
- **Adaptive Thresholds:** Adjust thresholds by time of day.  
- **Timers:** Add runtime countdowns using `input_number` entities.  
- **UI Controls:** Add Lovelace cards for quick toggles.  
- **Translations:** Expand beyond English for international use.  

---

## 🛠️ Development Workflow with VS Code + Copilot

1. Create the folder and empty files as listed above.  
2. In each file, write a short docstring describing its purpose.  
3. Use Copilot prompts like *“Implement a Home Assistant integration that monitors a sensor and triggers HVAC mode changes”*.  
4. Let Copilot scaffold the code, then refine it with comments and adjustments.  
5. Test incrementally — start with HVAC mode switching, then add fan, swing, humidity, and services.  
6. Use verbose logging during development to confirm behavior.  
7. Package the integration with a README and version number for sharing or HACS submission.  

---

## 📌 Next Steps

- Package as a GitHub repository.  
- Add unit tests with `pytest`.  
- Submit to HACS for community distribution.  
- Document usage examples and troubleshooting tips in the README.  
- Expand translations beyond English.  

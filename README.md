[![Stand With Ukraine](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner-direct-single.svg)](https://stand-with-ukraine.pp.ua)
[![Made in Ukraine](https://img.shields.io/badge/made_in-Ukraine-ffd700.svg?labelColor=0057b7)](https://stand-with-ukraine.pp.ua)
[![Stand With Ukraine](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/badges/StandWithUkraine.svg)](https://stand-with-ukraine.pp.ua)
[![Russian Warship Go Fuck Yourself](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/badges/RussianWarship.svg)](https://stand-with-ukraine.pp.ua)

[![GitHub Release][gh-release-image]][gh-release-url]
[![hacs][hacs-image]][hacs-url]

![logo](/icons/logo.png)

# 💡 Svitlo Yeah | Світло Є

A [Home Assistant][home-assistant] integration that tracks electricity outage schedules from Ukrainian energy providers,
providing outage calendars, countdown timers, and status updates.

###### [Цей документ українською](https://github-com.translate.goog/ALERTua/ha-svitlo-yeah/blob/main/README.md?_x_tr_sl=en&_x_tr_tl=uk&_x_tr_hl=en&_x_tr_pto=wapp)

## Supported Regions

| Region                         | Provider | Data Source                                                                                                                                                                                                                             |
|--------------------------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Kyiv**                       | DTEK     | [Yasno API](https://yasno.ua)                                                                                                                                                                                                           |
| **Dnipro**                     | DnEM     | [Yasno API](https://yasno.ua)                                                                                                                                                                                                           |
| **Dnipro**                     | CEK      | [Yasno API](https://yasno.ua)                                                                                                                                                                                                           |
| **Kyiv Oblast**                | DTEK     | [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua/blob/main/data/kyiv-region.json)                                                                                                                         |
| **Dnipro and Oblast**          | DTEK     | [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua/blob/main/data/dnipro.json)                                                                                                                              |
| **Odesa and Oblast**           | DTEK     | [Baskerville42/outage-data-ua](https://github.com/Baskerville42/outage-data-ua/blob/main/data/odesa.json)                                                                                                                               |
| **Khmelnytskyi and Oblast**    | KhOE     | [yaroslav2901/OE_OUTAGE_DATA](https://github.com/yaroslav2901/OE_OUTAGE_DATA/blob/main/data/Khmelnytskoblenerho.json)                                                                                                                   |
| **Ivano-Frankivsk and Oblast** | POE      | [yaroslav2901/OE_OUTAGE_DATA](https://github.com/yaroslav2901/OE_OUTAGE_DATA/blob/main/data/Prykarpattiaoblenerho.json)                                                                                                                 |
| **Uzhhorod and Oblast**        | ZOE      | [yaroslav2901/OE_OUTAGE_DATA](https://github.com/yaroslav2901/OE_OUTAGE_DATA/blob/main/data/Zakarpattiaoblenerho.json)                                                                                                                  |
| **Lviv and Oblast**            | LOE      | [yaroslav2901/OE_OUTAGE_DATA](https://github.com/yaroslav2901/OE_OUTAGE_DATA/blob/main/data/Lvivoblenerho.json)                                                                                                                         |
| **Ternopil and Oblast**        | TOE      | [yaroslav2901/OE_OUTAGE_DATA](https://github.com/yaroslav2901/OE_OUTAGE_DATA/blob/main/data/Ternopiloblenerho.json)                                                                                                                     |
| **Chernihiv and Oblast**       | ChOE     | [yaroslav2901/OE_OUTAGE_DATA](https://github.com/yaroslav2901/OE_OUTAGE_DATA/blob/main/data/Chernihivoblenergo.json)                                                                                                                    |
| **Zaporizhzhia and Oblast**    | ZOE      | [yaroslav2901/OE_OUTAGE_DATA](https://github.com/yaroslav2901/OE_OUTAGE_DATA/blob/main/data/Zaporizhzhiaoblenergo.json)                                                                                                                 |
| **Zhytomyr and Oblast**        | ZOE      | [yaroslav2901/OE_OUTAGE_DATA](https://github.com/yaroslav2901/OE_OUTAGE_DATA/blob/main/data/Zhytomyroblenergo.json)                                                                                                                     |
| **Polava and Oblast**          | POE      | [yaroslav2901/OE_OUTAGE_DATA](https://github.com/yaroslav2901/OE_OUTAGE_DATA/blob/main/data/Poltavaoblenergo.json)                                                                                                                      |
| **Rivne and Oblast**           | ROE      | [yaroslav2901/OE_OUTAGE_DATA](https://github.com/yaroslav2901/OE_OUTAGE_DATA/blob/main/data/Rivneoblenergo.json)                                                                                                                        |
| **Vinnytsia and Oblast**       | VOE      | [olnet93/gpv-voe-vinnytsia](https://github.com/olnet93/gpv-voe-vinnytsia/blob/main/data/Vinnytsiaoblenerho.json)<br/>[vn-progr/gpv-voe-vinnytsia](https://github.com/vn-progr/gpv-voe-vinnytsia/blob/main/data/Vinnytsiaoblenerho.json) |
| **Sumy and Oblast**            | SOE      | [E-Svitlo API](https://sm.e-svitlo.com.ua/)                                                                                                                                                                                             |

## Installation

The quickest way to install this integration is via [HACS][hacs-url] by clicking the button below:

[![Add to HACS via My Home Assistant][hacs-install-image]][hasc-install-url]

If it doesn't work, adding this repository to HACS manually by adding this URL:

1. Visit **HACS** → **Integrations** → **...** (in the top right) → **Custom repositories**
2. Click **Add**
3. Paste `https://github.com/ALERTua/ha-svitlo-yeah` into the **URL** field
4. Chose **Integration** as a **Category**
5. **Svitlo Yeah | Світло Є** will appear in the list of available integrations. Install it normally.

## Usage

This integration is configurable via UI. On **Devices and Services** page, click **Add Integration** and search for *
*Svitlo Yeah**.

### Select your region and Service Provider (if applicable)

![Region Selection](/media/1_region.png)

### Select your Group

![Group Selection](/media/3_group.png)

### Here's how the devices look

![Devices page](/media/4_devices.png)

### Sensors

![Sensors](/media/5_sensors.png) ![Sensors 2](/media/5_1_sensors.png)

### Calendar View

Then you can add the integration to your dashboard and see the information about the next planned outages.
Integration also provides a calendar view of planned outages. You can add it to your dashboard as well
via [Calendar card][calendar-card].

![Calendars view](/media/6_calendar.png)

### Examples

- [Automation](/examples/automation.yaml)
- [Dashboard](/examples/dashboard.yaml)

![dashboard](media/7_dashboard.png)

## Integration Entities

The integration creates the following entities in Home Assistant:

### Sensors

| Entity                                                                                   | Type             | Purpose                                                           | Description                                                                                                                                                                                                                                                                                                                                              |
|------------------------------------------------------------------------------------------|------------------|-------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Electricity**                                                                          | Enum Sensor      | Shows current power connectivity state according to the calendar  | Indicates the current electricity status with three possible states: `connected` (normal power), `planned_outage` (scheduled blackout), or `emergency` (unscheduled blackout). Reflects the calendar state and shows if there is an ongoing outage event at the moment. Provides additional attributes including event details when an outage is active. |
| [**Schedule Updated On**](/custom_components/svitlo_yeah/translations/uk.json#L97)       | Timestamp Sensor | Shows when outage schedule was last updated by the provider       | Displays the timestamp when the energy provider last updated the outage schedule on their servers. Reflects server-side data changes, not client fetch times.                                                                                                                                                                                            |
| [**Schedule Data Changed On**](/custom_components/svitlo_yeah/translations/uk.json#L100) | Timestamp Sensor | Shows when actual outage schedule data changed                    | Tracks the timestamp when the actual data was modified. Useful for notifications when schedules are updated. See examples.                                                                                                                                                                                                                               |
| [**Next Planned Outage**](/custom_components/svitlo_yeah/translations/uk.json#L104)      | Timestamp Sensor | Shows the start time of the next scheduled blackout               | Displays the timestamp when the next planned power outage is scheduled to begin. Null when no outages are scheduled.                                                                                                                                                                                                                                     |
| [**Next Scheduled Outage**](/custom_components/svitlo_yeah/translations/uk.json#L107)    | Timestamp Sensor | Shows the start time of the nearest outage (scheduled or planned) | Displays the timestamp of the nearest upcoming outage event, comparing scheduled outages and planned outages to show whichever comes first. Null when no outages are scheduled.                                                                                                                                                                          |
| [**Next Connectivity**](/custom_components/svitlo_yeah/translations/uk.json#L109)        | Timestamp Sensor | Shows when power is expected to return                            | Displays the timestamp when power connectivity is expected to be restored after an outage. Null when no outages are active.                                                                                                                                                                                                                              |

### Calendar

| Entity                         | Type            | Purpose                                           | Description                                                                                                                                                                                                                                                    |
|--------------------------------|-----------------|---------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Planned Outages Calendar**   | Calendar Entity | Provides calendar integration for planned outages | Shows all planned power outages as calendar events. Can be used with Home Assistant's calendar cards, automations, and triggers. Events include "Definite" planned outages and "Emergency" unscheduled blackouts. The calendar state is `on` during any event. |
| **Scheduled Outages Calendar** | Calendar Entity | Provides calendar integration for outage schedule | Shows the power outages schedule.                                                                                                                                                                                                                              |

### Events

| Event                        | Description                             |
|------------------------------|-----------------------------------------|
| **svitlo_yeah_data_changed** | Fired when outage data actually changes |

```yaml
event_type: svitlo_yeah_data_changed
data:
  region_name: Київ  # yes, Cyrillic. This is how it comes from the API
  region_id: 25
  provider_id: 902
  provider_name: ПРАТ «ДТЕК КИЇВСЬКІ ЕЛЕКТРОМЕРЕЖІ»
  group: "3.1"
  last_data_change: "2025-11-15T14:20:24.627353+02:00"
  config_entry_id: 01KB817HS8R32RSYH5RW01G78Z
```

```yaml
event_type: svitlo_yeah_data_changed
data:
  region_name: odesa
  region_id: null
  provider_id: null
  provider_name: null
  group: "1.1"
  last_data_change: "2025-11-15T14:20:24.627353+02:00"
  config_entry_id: 01KB817S4AXVFB39X97NGYCV55
```

### Entity Usage Examples

- Use the **Electricity** sensor in dashboards to display current power status from the calendar perspective
- Set up notifications when **Schedule Data Changed On** updates to alert about schedule changes
- Or use the event to trigger on (described above and in [automation examples](/examples/automation.yaml))
- Use the **Planned Outages Calendar** with calendar triggers for advance warnings before outages
- Monitor **Next Planned Outage** and **Next Connectivity** timestamps for countdown displays

### Caveats

- To get your Yasno group, you can use this [![video example](/media/yasno_group.gif)


## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for information about adding new regions and contributing to the project.

<!-- Badges -->

[gh-release-url]: https://github.com/ALERTua/ha-svitlo-yeah/releases/latest

[gh-release-image]: https://img.shields.io/github/v/release/ALERTua/ha-svitlo-yeah?style=flat-square

[gh-downloads-url]: https://github.com/ALERTua/ha-svitlo-yeah/releases

[hacs-url]: https://github.com/hacs/integration

[hacs-image]: https://img.shields.io/badge/hacs-default-orange.svg?style=flat-square

<!-- References -->

[home-assistant]: https://www.home-assistant.io/

[hasc-install-url]: https://my.home-assistant.io/redirect/hacs_repository/?owner=ALERTua&repository=ha-svitlo-yeah&category=integration

[hacs-install-image]: https://my.home-assistant.io/badges/hacs_repository.svg

[calendar-card]: https://www.home-assistant.io/dashboards/calendar/

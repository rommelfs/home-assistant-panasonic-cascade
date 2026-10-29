# Tested installation and software versions

This page records the equipment observed in the reference installation and the software used for validation. It is a compatibility record, not a guarantee for every Panasonic controller or heat pump.

## Reference installation

The reference installation is a two-unit Panasonic cascade used for space heating. The owner has reported using the integration in Home Assistant; the supplied entity-list screenshot shows discovered entities. The controller data below comes from the supplied web-interface captures.

| Component | Observed model or version | Evidence and scope |
| --- | --- | --- |
| Controller web interface | **P-SMART EDGE v5.1** | Page title in the captured project-selection interface. A patch/build number was not established. |
| Controller interface/API | Panasonic Cascade Control (`panCascadeControlExt`), local FIN/Haystack API | Captured overview, settings, equipment details, and alarm responses. The exact FIN runtime version was not established. |
| Unit 1 outdoor unit | **Panasonic WH-WXG09ME8**, **9 kW** | Controller equipment metadata; main unit in the cascade. |
| Unit 1 indoor/controller model field | **WH-CME8** | Resolved `iduModel` value returned by the controller. |
| Unit 2 outdoor unit | **Panasonic WH-WXG09ME8**, **9 kW** | Controller equipment metadata; second unit in the cascade. |
| Unit 2 indoor/controller model field | **Standalone** | Exact resolved `iduModel` value returned by the controller; no separate indoor-unit model is identified by this value. |
| Heating configuration | Space heating, Zone 1; domestic hot water unused | Owner-reported use. Domestic-hot-water visibility can be disabled in integration options. |
| Heat pump firmware | **Not recorded** | No reliable firmware version was identified in the supplied captures. |
| Installed Home Assistant / HACS versions | **Not recorded** | The installation's exact versions have not been supplied. The automated test version below is separate. |

These are the models identified so far. Other models, controller software versions, and mixed-model cascades have not been verified. Numeric model register codes are not additional tested models.

## Automated validation environment

| Component | Version | Validation scope |
| --- | --- | --- |
| Integration baseline | **0.5.2** | Published prerelease used as the baseline for this compatibility record; the owner's installed integration version is not confirmed. |
| Home Assistant Core | **2026.10.0** | Pinned development dependency; actual Home Assistant classes with a simulated controller backend. This does not establish a minimum supported Core version. |
| Python | **3.14** (local run: **3.14.6**) | Local test environment; CI selects Python 3.14. |
| Functional test suite | **82 passing tests** | Protocol, authentication, setup, entities, controls, dashboard storage, domestic-hot-water visibility, and alarm notifications to a local test receiver. |

Hassfest and HACS validation also passed for the 0.5.2 release. Their CI actions track upstream branches; they are validation tools, not controller software versions. See the [validation workflow](../.github/workflows/validate.yml) and [development requirements](../requirements-dev.txt).

## What has and has not been verified

- **Observed on the installation:** controller models and interface version above, captured operating/diagnostic data, and integration entities reported in the owner's Home Assistant UI.
- **Validated by capture replay and automated tests:** response parsing, optional diagnostics, dashboard generation, control request logic, authentication against test servers, and alarm notification handling.
- **Still requires live confirmation:** hardware writes such as Zone 1 on/off, the complete authentication/session-renewal lifecycle against this controller, and delivery of a real alarm notification to a phone. Phone model, iOS/Companion App versions, and end-to-end Apple push delivery have not been recorded.

A test receiver accepting a notification does not prove that a phone displayed it. Likewise, valid control requests in automated tests do not prove that hardware executed them. See [Validation and limitations](../README.md#validation-and-limitations) for the detailed scope.

## Reporting another tested configuration

When reporting compatibility, include the outdoor/indoor model identifiers, controller interface version and build if available, heat pump firmware if known, Home Assistant Core, HACS and integration versions, and the functions actually exercised. For phone notifications, also include the phone OS and Companion App versions and whether a test or real alarm was received.

Describe read-only operation, hardware control, and phone delivery separately. Omit addresses, installation identifiers, serial numbers, account details, session tokens, and unredacted HAR files from public reports.

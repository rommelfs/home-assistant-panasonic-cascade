"""Integration constants."""
DOMAIN = "panasonic_cascade"
PLATFORMS = ["sensor", "binary_sensor", "switch", "number", "select"]
DEFAULT_PROJECT = "pSmartEdge"
# Only regular UI controls, never emergency overrides or sterilization triggers.
BOOL_CONTROLS = {"sgReady", "stopRun"}
ENUM_CONTROLS = {"quietModeRequest", "bufferMode", "zone1Zone2OnOffSetpoint"}
# Conservative commissioning bounds for direct water-temperature setpoints.
NUMBER_CONTROLS = {
    "zone1WaterTemperatureHotSetpoint": (20, 55),
    "zone1WaterTemperatureColdSetpoint": (5, 25),
    "tankWaterTempSpBeforeSgReady": (40, 60),
}
STATUS_FIELDS = ("isConnected", "isOn", "isRunning", "isInAlarm", "isAvailableBuffer", "isAvailableTank", "run", "isEnabled")
COUNT_FIELDS = ("runningUnitsAmount", "requiredUnitsAmount", "availableUnitsAmount", "configuredUnitsAmount")

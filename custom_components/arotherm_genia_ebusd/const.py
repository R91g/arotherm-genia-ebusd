"""Constants for the aroTHERM & GeniaAir (eBUS) integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "arotherm_genia_ebusd"
MANUFACTURER_SAUNIER_DUVAL = "Saunier Duval"
MANUFACTURER_VAILLANT = "Vaillant"
MANUFACTURER = MANUFACTURER_SAUNIER_DUVAL
MANUFACTURERS: list[str] = [MANUFACTURER_SAUNIER_DUVAL, MANUFACTURER_VAILLANT]
DEFAULT_MANUFACTURER = MANUFACTURER_SAUNIER_DUVAL

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.WATER_HEATER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.DATETIME,
]

# Configuration keys and defaults (ConfigFlow)
CONF_MQTT_PREFIX = "mqtt_prefix"
DEFAULT_MQTT_PREFIX = "ebusd"

CONF_MANUFACTURER = "manufacturer"

CONF_OUTDOOR_MODEL = "outdoor_model"
DEFAULT_OUTDOOR_MODEL_SAUNIER = "GeniaAir Max ES 15"
DEFAULT_OUTDOOR_MODEL_VAILLANT = "aroTHERM plus ES VWL 155/7.1 A 230V"
DEFAULT_OUTDOOR_MODEL = DEFAULT_OUTDOOR_MODEL_SAUNIER

OUTDOOR_MODELS_SAUNIER: list[str] = [
    "GeniaAir Max ES 5",
    "GeniaAir Max ES 8",
    "GeniaAir Max ES 12",
    "GeniaAir Max ES 15",
    "GeniaAir Iso ES",
    "GeniaAir Max 4 (Legacy)",
    "GeniaAir Max 6 (Legacy)",
    "GeniaAir Max 8 (Legacy)",
    "GeniaAir Max 11 (Legacy)",
    "GeniaAir Max 15 (Legacy)",
]

OUTDOOR_MODELS_VAILLANT: list[str] = [
    "aroTHERM plus ES VWL 55/7.1 A 230V",
    "aroTHERM plus ES VWL 85/7.1 A 230V",
    "aroTHERM plus ES VWL 125/7.1 A 230V",
    "aroTHERM plus ES VWL 125/7.1 A 400V",
    "aroTHERM plus ES VWL 155/7.1 A 230V",
    "aroTHERM plus ES VWL 155/7.1 A 400V",
    "aroTHERM plus VWL 35/6 A 230V (Legacy)",
    "aroTHERM plus VWL 55/6 A 230V (Legacy)",
    "aroTHERM plus VWL 75/6 A 230V (Legacy)",
    "aroTHERM plus VWL 105/6 A 230V (Legacy)",
    "aroTHERM plus VWL 125/6 A (Legacy)",
]

OUTDOOR_MODELS: list[str] = OUTDOOR_MODELS_SAUNIER + OUTDOOR_MODELS_VAILLANT

OUTDOOR_MODELS_BY_MANUFACTURER: dict[str, list[str]] = {
    MANUFACTURER_SAUNIER_DUVAL: OUTDOOR_MODELS_SAUNIER,
    MANUFACTURER_VAILLANT: OUTDOOR_MODELS_VAILLANT,
}

OUTDOOR_MODEL_SPECS: dict[str, str] = {
    "GeniaAir Max ES 5": "GeniaAir Max ES 5 (HA 5-7.1 O 230V B3)",
    "GeniaAir Max ES 8": "GeniaAir Max ES 8 (HA 8-7.1 O 230V B3)",
    "GeniaAir Max ES 12": "GeniaAir Max ES 12 (HA 12-7.1 O 230V B3)",
    "GeniaAir Max ES 15": "GeniaAir Max ES 15 (HA 15-7.1 O 230V B3)",
    "GeniaAir Iso ES": "GeniaAir Iso ES (HA 7.1 O 230V)",
    "GeniaAir Max 4 (Legacy)": "GeniaAir Max 4 (HA 4-5/2 230V R290)",
    "GeniaAir Max 6 (Legacy)": "GeniaAir Max 6 (HA 6-5/2 230V R290)",
    "GeniaAir Max 8 (Legacy)": "GeniaAir Max 8 (HA 8-5/2 230V R290)",
    "GeniaAir Max 11 (Legacy)": "GeniaAir Max 11 (HA 11-5/2 230V R290)",
    "GeniaAir Max 15 (Legacy)": "GeniaAir Max 15 (HA 15-5/2 230V R290)",
    "aroTHERM plus ES VWL 55/7.1 A 230V": "aroTHERM plus ES VWL 55/7.1 A 230V S3 (R290)",
    "aroTHERM plus ES VWL 85/7.1 A 230V": "aroTHERM plus ES VWL 85/7.1 A 230V S3 (R290)",
    "aroTHERM plus ES VWL 125/7.1 A 230V": "aroTHERM plus ES VWL 125/7.1 A 230V S3 (R290)",
    "aroTHERM plus ES VWL 125/7.1 A 400V": "aroTHERM plus ES VWL 125/7.1 A 400V S3 (R290)",
    "aroTHERM plus ES VWL 155/7.1 A 230V": "aroTHERM plus ES VWL 155/7.1 A 230V S3 (R290)",
    "aroTHERM plus ES VWL 155/7.1 A 400V": "aroTHERM plus ES VWL 155/7.1 A 400V S3 (R290)",
    "aroTHERM plus VWL 35/6 A 230V (Legacy)": "aroTHERM plus VWL 35/6 A 230V S3 (R290)",
    "aroTHERM plus VWL 55/6 A 230V (Legacy)": "aroTHERM plus VWL 55/6 A 230V S3 (R290)",
    "aroTHERM plus VWL 75/6 A 230V (Legacy)": "aroTHERM plus VWL 75/6 A 230V S3 (R290)",
    "aroTHERM plus VWL 105/6 A 230V (Legacy)": "aroTHERM plus VWL 105/6 A 230V S3 (R290)",
    "aroTHERM plus VWL 125/6 A (Legacy)": "aroTHERM plus VWL 125/6 A S3 (R290)",
}

CONF_INDOOR_MODEL = "indoor_model"
DEFAULT_INDOOR_MODEL_SAUNIER = "HPIM 7 230V"
DEFAULT_INDOOR_MODEL_VAILLANT = "VWZ MEH 97/7"
DEFAULT_INDOOR_MODEL = DEFAULT_INDOOR_MODEL_SAUNIER

INDOOR_MODELS_SAUNIER: list[str] = [
    "HPIM 7 230V",
    "GeniaSet FEW/FIW 200-7",
    "Módulo Hidráulico HE 9-7 W",
]

INDOOR_MODELS_VAILLANT: list[str] = [
    "VWZ MEH 97/7",
    "uniTOWER VIH QW 190/7",
    "VWZ MH 97/7",
    "VWZ AI 7/230V",
]

INDOOR_MODELS: list[str] = INDOOR_MODELS_SAUNIER + INDOOR_MODELS_VAILLANT

INDOOR_MODELS_BY_MANUFACTURER: dict[str, list[str]] = {
    MANUFACTURER_SAUNIER_DUVAL: INDOOR_MODELS_SAUNIER,
    MANUFACTURER_VAILLANT: INDOOR_MODELS_VAILLANT,
}

INDOOR_MODEL_SPECS: dict[str, str] = {
    "HPIM 7 230V": "HPIM 7 230V (VWZIO 8000033994)",
    "GeniaSet FEW/FIW 200-7": "GeniaSet FEW/FIW 200-7 (VWZIO)",
    "Módulo Hidráulico HE 9-7 W": "Módulo Hidráulico HE 9-7 W (VWZIO)",
    "VWZ MEH 97/7": "Módulo Hidráulico Mural VWZ MEH 97/7 (VWZIO)",
    "uniTOWER VIH QW 190/7": "Torre Hidráulica uniTOWER VIH QW 190/7 (VWZIO)",
    "VWZ MH 97/7": "Módulo Hidráulico VWZ MH 97/7 (VWZIO)",
    "VWZ AI 7/230V": "Interfaz de Bomba VWZ AI /7 230V (VWZIO)",
}

CONF_HAS_WIRELESS_ROOM_UNIT = "has_wireless_room_unit"
DEFAULT_HAS_WIRELESS_ROOM_UNIT = True

CONF_HAS_MIGO_LINK = "has_migo_link"
DEFAULT_HAS_MIGO_LINK = True

# Options keys and defaults (OptionsFlow)
CONF_FORCE_DHW_BOOST = "force_dhw_boost"
DEFAULT_FORCE_DHW_BOOST = True

DHW_BOOST_HYST_MARGIN = 1.5

CONF_AUTO_COOLING_LOCK_BYPASS = "auto_cooling_lock_bypass"
DEFAULT_AUTO_COOLING_LOCK_BYPASS = True

CONF_FALLBACK_POLL_INTERVAL = "fallback_poll_interval"
DEFAULT_FALLBACK_POLL_INTERVAL = 300

# Logical Device Identifiers
DEVICE_OUTDOOR_UNIT = "outdoor_unit"
DEVICE_CLIMATE_CONTROLLER = "climate_controller"
DEVICE_HYDRAULIC_INTERFACE = "hydraulic_interface"
DEVICE_WIRELESS_THERMOSTAT = "wireless_thermostat"

# eBUS Circuits
CIRCUIT_HMUX0 = "hmux0"
CIRCUIT_BASS3 = "bass3"
CIRCUIT_VWZIO = "vwzio"
CIRCUIT_NETX3 = "04"
CIRCUIT_NETX3_ALT = "f6"
CIRCUIT_BROADCAST = "broadcast"
CIRCUIT_GLOBAL = "global"

# eBUS Scan address mapping for passive hardware & software version detection
SCAN_ADDRESS_TO_DEVICE_KEY: dict[str, str] = {
    "08": DEVICE_OUTDOOR_UNIT,
    "15": DEVICE_CLIMATE_CONTROLLER,
    "76": DEVICE_HYDRAULIC_INTERFACE,
    "04": DEVICE_WIRELESS_THERMOSTAT,
    "f6": DEVICE_WIRELESS_THERMOSTAT,
}

SCAN_TOPIC_CIRCUITS: tuple[str, ...] = (
    "scan.08",
    "scan.15",
    "scan.76",
    "scan.04",
    "scan.f6",
    "Scan.08",
    "Scan.15",
    "Scan.76",
    "Scan.04",
    "Scan.f6",
)

# Fallback hardware and software versions if scan has not arrived yet
DEFAULT_DEVICE_VERSIONS: dict[str, dict[str, str]] = {
    DEVICE_OUTDOOR_UNIT: {"sw": "0407", "hw": "0504"},
    DEVICE_CLIMATE_CONTROLLER: {"sw": "0708", "hw": "4304"},
    DEVICE_HYDRAULIC_INTERFACE: {"sw": "0500", "hw": "0504"},
    DEVICE_WIRELESS_THERMOSTAT: {"sw": "0129", "hw": "0404"},
}

# Calculated virtual sensor keys stored under ("calculated", <key>)
CALC_CIRCUIT = "calculated"
CALC_DELTA_T = "calculated_delta_t"
CALC_THERMAL_POWER = "calculated_thermal_power"
CALC_LIVE_COP = "calculated_live_cop"
CALC_HC_COP = "calculated_hc_cop"
CALC_HWC_COP = "calculated_hwc_cop"
CALC_COOL_EER = "calculated_cool_eer"
CALC_GLOBAL_EFFICIENCY = "calculated_global_efficiency"
CALC_HEATING_TOTAL_ENERGY = "calculated_heating_total_energy"
CALC_DHW_TOTAL_ENERGY = "calculated_dhw_total_energy"
CALC_SYSTEM_TOTAL_ENERGY = "calculated_system_total_energy"

# Deprecated unique_id suffixes automatically removed from entity_registry on setup
DEPRECATED_UNIQUE_ID_SUFFIXES: tuple[str, ...] = (
    "calculated_calculated_daily_cop_value",
    "calculated_calculated_monthly_cop_value",
    "calculated_calculated_total_cop_value",
    "calculated_calculated_total_energy_value",
    "hmux0_prenergyelectrictoday_energy",
    "hmux0_prenergyelectricmonth_energy",
    "hmux0_prenergyelectrictotal_energy",
    "hmux0_prenergycoolingelectrictoday_energy",
    "hmux0_prenergycoolingelectricmonth_energy",
    "hmux0_prenergycoolingelectrictotal_energy",
    "hmux0_prenergythermaltoday_energy",
    "hmux0_prenergythermalmonth_energy",
    "hmux0_prenergythermaltotal_energy",
    "hmux0_prenergyheatingtoday_energy",
    "hmux0_prenergyheatingmonth_energy",
    "hmux0_prenergyheatingtotal_energy",
    "binary_hmux0_energyyieldprecision_status",
)

# Timing & Hydration Constants
# Note: Physical eBUS runs at 2400 baud (~240 bytes/s). The delays below ensure reliable
# bus arbitration, avoiding collision storms with physical wall controls (MiPro Sense).
INITIAL_HYDRATION_WAIT_SECONDS = 5.0
HYDRATION_STEP_DELAY_SECONDS = 0.8
SET_CONFIRMATION_DELAY_SECONDS = 1.5
DHW_BOOST_MAX_TIMEOUT_SECONDS = 3600  # 60 minutes safety timeout

# Firmware Sentinel Thresholds
SENTINEL_COOLING_OFF_TEMP = 99.0
SENTINEL_COOLING_THRESHOLD = 40.0
SENTINEL_HEATING_OFF_TEMP = 5.0
SENTINEL_HEATING_THRESHOLD = 5.5
DEFAULT_COMFORT_TEMP = 22.0
DEFAULT_COOLING_TEMP = 23.0
DEFAULT_CYLINDER_HYST = 5.0

# Services
SERVICE_SET_WEEKLY_TIMER = "set_weekly_timer"
SERVICE_FORCE_DHW_BOOST = "force_dhw_boost"
SERVICE_SET_HOLIDAY_MODE = "set_holiday_mode"
SERVICE_CANCEL_HOLIDAY_MODE = "cancel_holiday_mode"

# Presets
PRESET_COMFORT = "comfort"
PRESET_MANUAL = "manual"
PRESET_ECO = "eco"
PRESET_BOOST = "boost"
PRESET_AWAY = "away"

# Holiday / Away Mode defaults and sentinels
DEFAULT_HOLIDAY_TEMP = 15.0
HOLIDAY_RESET_DATE = "01;01;15"
HOLIDAY_RESET_TIME = "00;00;00"
HOLIDAY_INDEFINITE_END_DATE = "01;01;99"
HOLIDAY_DEFAULT_END_TIME = "23;59;59"

# Days of week mapping for b5 55 timers
WEEKDAYS_LIST: list[str] = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

DAY_SHORT_KEYS: dict[str, str] = {
    "Monday": "mon",
    "Tuesday": "tue",
    "Wednesday": "wed",
    "Thursday": "thu",
    "Friday": "fri",
    "Saturday": "sat",
    "Sunday": "sun",
}

TIMER_CIRCUIT_PREFIXES: dict[str, str] = {
    "heating": "Z1Timer",
    "dhw": "HwcTimer",
    "cooling": "CoolingTimer",
    "circulation": "CirculationTimer",
}

# Essential eBUSd messages for Initial Staggered Hydration (/get queue)
# ONLY messages with active read priority (r / r1..r9) on the physical bus.
# Purely passive ('u') messages (temperatures, modes, runstats) are populated
# automatically via retained MQTT topics and periodic master broadcasts (f1 / 10).
ESSENTIAL_HYDRATION_MESSAGES: list[tuple[str, str]] = [
    # Climate Controller (15.bass3) - Actively readable setpoints, offsets & energy counters (r9)
    (CIRCUIT_BASS3, "Z1NightTemp"),
    (CIRCUIT_BASS3, "Z1QuickVetoTemp"),
    (CIRCUIT_BASS3, "CoolingReleaseStatus"),
    (CIRCUIT_BASS3, "HwcSFMode"),
    (CIRCUIT_BASS3, "HwcFlowTemp"),
    (CIRCUIT_BASS3, "Hc1HeatCurve"),
    (CIRCUIT_BASS3, "Hc1ExcessTemp"),
    (CIRCUIT_BASS3, "Hc1MinFlowTempDesired"),
    (CIRCUIT_BASS3, "Hc1MaxFlowTempDesired"),
    (CIRCUIT_BASS3, "Hc1SummerTempLimit"),
    (CIRCUIT_BASS3, "CoolingFlowTempDesiredMin"),
    (CIRCUIT_BASS3, "CoolingFlowTempDesiredMax"),
    (CIRCUIT_BASS3, "Hc1AutoOffMode"),
    (CIRCUIT_BASS3, "Hc1RoomTempSwitchOn"),
    (CIRCUIT_BASS3, "HwcMaxFlowTempDesired"),
    (CIRCUIT_BASS3, "CylinderChargeHyst"),
    (CIRCUIT_BASS3, "CylinderChargeOffset"),
    (CIRCUIT_BASS3, "MaxCylinderChargeTime"),
    (CIRCUIT_BASS3, "HwcLockTime"),
    (CIRCUIT_BASS3, "HwcParallelLoading"),
    (CIRCUIT_BASS3, "AdaptHeatCurve"),
    (CIRCUIT_BASS3, "BufferChargeOffset"),
    (CIRCUIT_BASS3, "MaxRoomHumidity"),
    (CIRCUIT_BASS3, "BivalencePointHc"),
    (CIRCUIT_BASS3, "BivalencePointHwc"),
    (CIRCUIT_BASS3, "AlternativePoint"),
    (CIRCUIT_BASS3, "PrEnergySumHcThisMonth"),
    (CIRCUIT_BASS3, "PrEnergySumHcLastMonth"),
    (CIRCUIT_BASS3, "PrEnergySumHc"),
    (CIRCUIT_BASS3, "PrEnergySumHwcThisMonth"),
    (CIRCUIT_BASS3, "PrEnergySumHwcLastMonth"),
    (CIRCUIT_BASS3, "PrEnergySumHwc"),
    # Outdoor Unit (08.hmux0) - Active live telemetry & energy counters (r / r1..r9)
    (CIRCUIT_HMUX0, "PowerStatus"),
    (CIRCUIT_HMUX0, "RunDataElectricPowerConsumption"),
    (CIRCUIT_HMUX0, "RunDataHighPressure"),
    (CIRCUIT_HMUX0, "RunDataFlowTemp"),
    (CIRCUIT_HMUX0, "RunDataReturnTemp"),
    (CIRCUIT_HMUX0, "RunDataAirInletTemp"),
    (CIRCUIT_HMUX0, "RunDataCompressorInletTemp"),
    (CIRCUIT_HMUX0, "RunDataCompressorOutletTemp"),
    (CIRCUIT_HMUX0, "RunDataEEVOutletTemp"),
    (CIRCUIT_HMUX0, "PrEnergyElectricHc"),
    (CIRCUIT_HMUX0, "PrEnergyElectricHwc"),
    (CIRCUIT_HMUX0, "PrEnergyElectricCool"),
    (CIRCUIT_HMUX0, "PrEnergyThermalHc"),
    (CIRCUIT_HMUX0, "PrEnergyThermalHwc"),
    (CIRCUIT_HMUX0, "PrEnergyThermalCool"),
    (CIRCUIT_HMUX0, "PrEnergyEnvYieldHc"),
    (CIRCUIT_HMUX0, "PrEnergyEnvYieldHwc"),
    # Hydraulic Interface (76.vwzio) - Active power & energy counters (r)
    (CIRCUIT_VWZIO, "PowerStatus"),
    (CIRCUIT_VWZIO, "PrEnergyElectricHc"),
    (CIRCUIT_VWZIO, "PrEnergyElectricHwc"),
    (CIRCUIT_VWZIO, "PrEnergyThermalHc"),
    (CIRCUIT_VWZIO, "PrEnergyThermalHwc"),
]

# All 52 HMUStatusCode values (plus normalized aliases)
HMU_STATUS_CODES: list[str] = [
    "frost_protect",
    "standby",
    "heat_compressor_shutdown",
    "heat_compressor_blocked",
    "heat_prerun",
    "heat_compressor_active",
    "heat_overrun",
    "cool_compressor_shutdown",
    "cool_compressor_blocked",
    "cool_prerun",
    "cool_compressor_active",
    "cool_overrun",
    "heat_immersion_heater_active",
    "heat_immersion_active",
    "hwc_compressor_blocked",
    "hwc_prerun",
    "hwc_compressor_active",
    "hwc_immersion_heater_active",
    "hwc_immersion_active",
    "hwc_overrun",
    "heat_immersion_heater_shutdown",
    "heat_immersion_heater_blocked",
    "hwc_immersion_heater_shutdown",
    "hwc_immersion_heater_blocked",
    "air_purging_program_active",
    "compressor_oil_heating_active",
    "fan1_blocked",
    "fan1_airinlet_too_high",
    "fan1_airinlet_too_low",
    "fan2_blocked",
    "building_circuit_flow_too_low",
    "building_circuit_pump_fault",
    "frequency_converter_fault_compressor",
    "frequency_converter_fault_mains_voltage",
    "frequency_converter_fault_overheating",
    "deicing_time_too_long",
    "deicing_flow_temp_too_low",
    "compressor_outlet_temp_too_high",
    "hot_gas_temp_switch_open",
    "fan1_wind",
    "fan2_wind",
    "current_limt_active",
    "high_pressure_switch_open",
    "compressor_outlet_temp_too_high_1",
    "evaporation_temp_too_low",
    "condensation_temp_too_low",
    "evaporation_temp_too_high",
    "condensation_temp_too_high",
    "building_circuit_return_temp_too_low",
    "building_circuit_return_temp_too_high",
    "immersion_heater_flow_temp_too_high",
    "deicing_active",
    "deicing",
    "frequency_converter_fault",
    "connection_fault_frequency_converter",
    "four_port_valve_position_fault",
]

SYSTEM_OPERATING_STATES: list[str] = [
    "standby",
    "heating",
    "cooling",
    "dhw",
]

Z1_STATUS_OPTIONS: list[str] = [
    "auto",
    "ventilation",
    "veto",
    "holidayaway",
    "load",
    "off",
]

HWC_STATUS_OPTIONS: list[str] = [
    "auto",
    "holidayaway",
    "load",
    "off",
]

SETMODE_HC_MODES: list[str] = [
    "auto",
    "off",
    "heat",
    "water",
]

VWZIO_SECONDARY_STATUS_OPTIONS: list[str] = [
    "standby",
    "heating",
    "cooling",
    "dhw",
    "overrun",
]

VWZIO_SECONDARY_HWC_OPTIONS: list[str] = [
    "standby",
    "dhw",
]

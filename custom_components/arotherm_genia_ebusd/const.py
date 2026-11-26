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
    Platform.TIME,
    Platform.BUTTON,
    Platform.CALENDAR,
]

# Configuration keys and defaults (ConfigFlow)
CONF_PREREQUISITES_CONFIRMED = "confirm_prerequisites"
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
    "GeniaAir Max 4",
    "GeniaAir Max 6",
    "GeniaAir Max 8",
    "GeniaAir Max 11",
    "GeniaAir Max 15",
]

OUTDOOR_MODELS_VAILLANT: list[str] = [
    # aroTHERM plus ES (Spain / International /7.1 A)
    "aroTHERM plus ES VWL 55/7.1 A 230V",
    "aroTHERM plus ES VWL 85/7.1 A 230V",
    "aroTHERM plus ES VWL 125/7.1 A 230V",
    "aroTHERM plus ES VWL 125/7.1 A 400V",
    "aroTHERM plus ES VWL 155/7.1 A 230V",
    "aroTHERM plus ES VWL 155/7.1 A 400V",
    # aroTHERM pro (UK /7.1 A)
    "aroTHERM pro VWL 55/7.1 A 230V",
    "aroTHERM pro VWL 85/7.1 A 230V",
    "aroTHERM pro VWL 125/7.1 A 230V",
    "aroTHERM pro VWL 125/7.1 A 400V",
    "aroTHERM pro VWL 155/7.1 A 230V",
    "aroTHERM pro VWL 155/7.1 A 400V",
    # aroTHERM plus /8.1 A (v2)
    "aroTHERM plus VWL 35/8.1 A 230V",
    "aroTHERM plus VWL 55/8.1 A 230V",
    "aroTHERM plus VWL 75/8.1 A 230V",
    "aroTHERM plus VWL 105/8.1 A 230V",
    "aroTHERM plus VWL 105/8.1 A 400V",
    "aroTHERM plus VWL 125/8.1 A 230V",
    "aroTHERM plus VWL 125/8.1 A 400V",
    # aroTHERM plus /6 A (2020)
    "aroTHERM plus VWL 35/6 A 230V",
    "aroTHERM plus VWL 55/6 A 230V",
    "aroTHERM plus VWL 75/6 A 230V",
    "aroTHERM plus VWL 105/6 A 230V",
    "aroTHERM plus VWL 125/6 A 230V",
    "aroTHERM plus VWL 125/6 A",
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
    "GeniaAir Max 4": "GeniaAir Max 4 (HA 4-5/2 230V R290)",
    "GeniaAir Max 6": "GeniaAir Max 6 (HA 6-5/2 230V R290)",
    "GeniaAir Max 8": "GeniaAir Max 8 (HA 8-5/2 230V R290)",
    "GeniaAir Max 11": "GeniaAir Max 11 (HA 11-5/2 230V R290)",
    "GeniaAir Max 15": "GeniaAir Max 15 (HA 15-5/2 230V R290)",
    "GeniaAir Max 4 (Legacy)": "GeniaAir Max 4 (HA 4-5/2 230V R290)",
    "GeniaAir Max 6 (Legacy)": "GeniaAir Max 6 (HA 6-5/2 230V R290)",
    "GeniaAir Max 8 (Legacy)": "GeniaAir Max 8 (HA 8-5/2 230V R290)",
    "GeniaAir Max 11 (Legacy)": "GeniaAir Max 11 (HA 11-5/2 230V R290)",
    "GeniaAir Max 15 (Legacy)": "GeniaAir Max 15 (HA 15-5/2 230V R290)",
    # aroTHERM plus ES /7.1 A
    "aroTHERM plus ES VWL 55/7.1 A 230V": "aroTHERM plus ES VWL 55/7.1 A 230V S3 (R290)",
    "aroTHERM plus ES VWL 85/7.1 A 230V": "aroTHERM plus ES VWL 85/7.1 A 230V S3 (R290)",
    "aroTHERM plus ES VWL 125/7.1 A 230V": "aroTHERM plus ES VWL 125/7.1 A 230V S3 (R290)",
    "aroTHERM plus ES VWL 125/7.1 A 400V": "aroTHERM plus ES VWL 125/7.1 A 400V S3 (R290)",
    "aroTHERM plus ES VWL 155/7.1 A 230V": "aroTHERM plus ES VWL 155/7.1 A 230V S3 (R290)",
    "aroTHERM plus ES VWL 155/7.1 A 400V": "aroTHERM plus ES VWL 155/7.1 A 400V S3 (R290)",
    # aroTHERM pro /7.1 A
    "aroTHERM pro VWL 55/7.1 A 230V": "aroTHERM pro VWL 55/7.1 A 230V S3 (R290)",
    "aroTHERM pro VWL 85/7.1 A 230V": "aroTHERM pro VWL 85/7.1 A 230V S3 (R290)",
    "aroTHERM pro VWL 125/7.1 A 230V": "aroTHERM pro VWL 125/7.1 A 230V S3 (R290)",
    "aroTHERM pro VWL 125/7.1 A 400V": "aroTHERM pro VWL 125/7.1 A 400V S3 (R290)",
    "aroTHERM pro VWL 155/7.1 A 230V": "aroTHERM pro VWL 155/7.1 A 230V S3 (R290)",
    "aroTHERM pro VWL 155/7.1 A 400V": "aroTHERM pro VWL 155/7.1 A 400V S3 (R290)",
    # aroTHERM plus /8.1 A (v2)
    "aroTHERM plus VWL 35/8.1 A 230V": "aroTHERM plus VWL 35/8.1 A 230V S3 (R290)",
    "aroTHERM plus VWL 55/8.1 A 230V": "aroTHERM plus VWL 55/8.1 A 230V S3 (R290)",
    "aroTHERM plus VWL 75/8.1 A 230V": "aroTHERM plus VWL 75/8.1 A 230V S3 (R290)",
    "aroTHERM plus VWL 105/8.1 A 230V": "aroTHERM plus VWL 105/8.1 A 230V S3 (R290)",
    "aroTHERM plus VWL 105/8.1 A 400V": "aroTHERM plus VWL 105/8.1 A 400V S3 (R290)",
    "aroTHERM plus VWL 125/8.1 A 230V": "aroTHERM plus VWL 125/8.1 A 230V S3 (R290)",
    "aroTHERM plus VWL 125/8.1 A 400V": "aroTHERM plus VWL 125/8.1 A 400V S3 (R290)",
    # aroTHERM plus /6 A
    "aroTHERM plus VWL 35/6 A 230V": "aroTHERM plus VWL 35/6 A 230V S3 (R290)",
    "aroTHERM plus VWL 55/6 A 230V": "aroTHERM plus VWL 55/6 A 230V S3 (R290)",
    "aroTHERM plus VWL 75/6 A 230V": "aroTHERM plus VWL 75/6 A 230V S3 (R290)",
    "aroTHERM plus VWL 105/6 A 230V": "aroTHERM plus VWL 105/6 A 230V S3 (R290)",
    "aroTHERM plus VWL 125/6 A 230V": "aroTHERM plus VWL 125/6 A 230V S3 (R290)",
    "aroTHERM plus VWL 125/6 A": "aroTHERM plus VWL 125/6 A S3 (R290)",
    # Legacy strings
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
    "Hydraulic Module HE 9-7 W",
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
    "Hydraulic Module HE 9-7 W": "Hydraulic Module HE 9-7 W (VWZIO)",
    "Módulo Hidráulico HE 9-7 W": "Hydraulic Module HE 9-7 W (VWZIO)",
    "VWZ MEH 97/7": "Wall-Hung Hydraulic Module VWZ MEH 97/7 (VWZIO)",
    "uniTOWER VIH QW 190/7": "Hydraulic Tower uniTOWER VIH QW 190/7 (VWZIO)",
    "VWZ MH 97/7": "Hydraulic Module VWZ MH 97/7 (VWZIO)",
    "VWZ AI 7/230V": "Heat Pump Interface VWZ AI /7 230V (VWZIO)",
}

CONF_HAS_WIRELESS_ROOM_UNIT = "has_wireless_room_unit"
DEFAULT_HAS_WIRELESS_ROOM_UNIT = True

CONF_HAS_MIGO_LINK = "has_migo_link"
DEFAULT_HAS_MIGO_LINK = True

CONF_HAS_VR70 = "has_vr70"
DEFAULT_HAS_VR70 = False

# Options keys and defaults (OptionsFlow)
CONF_FORCE_DHW_BOOST = "force_dhw_boost"
DEFAULT_FORCE_DHW_BOOST = True

DHW_BOOST_HYST_MARGIN = 1.5

CONF_AUTO_COOLING_LOCK_BYPASS = "auto_cooling_lock_bypass"
DEFAULT_AUTO_COOLING_LOCK_BYPASS = True

CONF_FALLBACK_POLL_INTERVAL = "fallback_poll_interval"
DEFAULT_FALLBACK_POLL_INTERVAL = 300

SECTION_ADVANCED_OPTIONS = "advanced_options"

CONF_ENABLE_EBUSD_TCP = "enable_ebusd_tcp"
DEFAULT_ENABLE_EBUSD_TCP = False

CONF_EBUSD_TCP_HOST = "ebusd_tcp_host"
DEFAULT_EBUSD_TCP_HOST = "127.0.0.1"

CONF_EBUSD_TCP_PORT = "ebusd_tcp_port"
DEFAULT_EBUSD_TCP_PORT = 8888

CONF_ENABLE_SEND_HEX = "enable_send_hex"
DEFAULT_ENABLE_SEND_HEX = False
CONF_ENABLE_SCHEDULE_CALENDARS = "enable_schedule_calendars"
DEFAULT_ENABLE_SCHEDULE_CALENDARS = True

# Logical Device Identifiers
DEVICE_OUTDOOR_UNIT = "outdoor_unit"
DEVICE_CLIMATE_CONTROLLER = "climate_controller"
DEVICE_HYDRAULIC_INTERFACE = "hydraulic_interface"
DEVICE_WIRELESS_THERMOSTAT = "wireless_thermostat"
DEVICE_MIXER_MODULE = "mixer_module"

# eBUS Circuits
CIRCUIT_HMUX0 = "hmux0"
CIRCUIT_HMU = "hmu"
CIRCUIT_HMU00 = "hmu00"
OUTDOOR_CIRCUITS: tuple[str, ...] = (CIRCUIT_HMUX0, CIRCUIT_HMU, CIRCUIT_HMU00)
CIRCUIT_BASS3 = "bass3"
CIRCUIT_BASV3 = "basv3"
CIRCUIT_CTLV2 = "ctlv2"
CIRCUIT_CTLV3 = "ctlv3"
CONTROLLER_CIRCUITS: tuple[str, ...] = (
    CIRCUIT_BASS3,
    CIRCUIT_BASV3,
    CIRCUIT_CTLV2,
    CIRCUIT_CTLV3,
)
# Controllers whose b5 55 schedule firmware enforces 10-minute time increments
TEN_MINUTE_STEP_CONTROLLER_CIRCUITS: frozenset[str] = frozenset({CIRCUIT_CTLV2})
CIRCUIT_VWZIO = "vwzio"
CIRCUIT_VR70 = "vr_70"
CIRCUIT_NETX3 = "04"
CIRCUIT_NETX3_ALT = "f6"
CIRCUIT_BROADCAST = "broadcast"
CIRCUIT_GLOBAL = "global"

# Cross-circuit and traditional eBUSd message name normalization aliases
MESSAGE_ALIASES: dict[str, str] = {
    "flowtemp": "RunDataFlowTemp",
    "buildingcircuitflow": "RunDataFlowRate",
    "waterthroughput": "RunDataFlowRate",
    "rundatastatuscode": "HMUStatusCode",
    "powerconsumptionhmu": "RunDataElectricPowerConsumption",
    "z1maxflowtempdesired": "Z1RoomHumidity",
    "rundataenergyintegral": "EnergyIntegral",
    "energyintegral": "EnergyIntegral",
    "runstatshcstarts": "RunStatsAuxHeaterSwitches",
    "rundatanominalflowrate": "RunDataMaxResidualHead",
    "coolingflowtempdesiredmax": "EmergencyFlowTempDesired",
}

# Weekly timer passive update aliases for eavesdropping MiGo Link / gateway writes
for _day in (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
):
    MESSAGE_ALIASES[f"z1timer_{_day.lower()}_passive"] = f"Z1Timer_{_day}"
    MESSAGE_ALIASES[f"z1timer_{_day.lower()}_slot2_passive"] = f"Z1Timer_{_day}_Slot2"
    MESSAGE_ALIASES[f"z1timer_{_day.lower()}_slot3_passive"] = f"Z1Timer_{_day}_Slot3"

# eBUS Scan address mapping for passive hardware & software version detection
SCAN_ADDRESS_TO_DEVICE_KEY: dict[str, str] = {
    "08": DEVICE_OUTDOOR_UNIT,
    "15": DEVICE_CLIMATE_CONTROLLER,
    "52": DEVICE_MIXER_MODULE,
    "76": DEVICE_HYDRAULIC_INTERFACE,
    "04": DEVICE_WIRELESS_THERMOSTAT,
    "f6": DEVICE_WIRELESS_THERMOSTAT,
}

SCAN_TOPIC_CIRCUITS: tuple[str, ...] = (
    "scan.08",
    "scan.15",
    "scan.52",
    "scan.76",
    "scan.04",
    "scan.f6",
    "Scan.08",
    "Scan.15",
    "Scan.52",
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
    "number_bass3_z1daytemp_value",
    "number_bass3_z1coolingtempdesired_value",
    "number_basv3_z1daytemp_value",
    "number_basv3_z1coolingtempdesired_value",
    "number_ctlv2_z1daytemp_value",
    "number_ctlv2_z1coolingtempdesired_value",
    "number_ctlv3_z1daytemp_value",
    "number_ctlv3_z1coolingtempdesired_value",
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
    "hmux0_statecompressor_comp_speed",
    "binary_hmux0_statecompressor_comp_speed",
    "bass3_coolingstartdate_day;month;year",
    "bass3_coolingenddate_day;month;year",
    "bass3_holidaystartdate_day;month;year",
    "bass3_holidayenddate_day;month;year",
    "number_bass3_coolingflowtempdesiredmax_value",
    "number_basv3_coolingflowtempdesiredmax_value",
    "number_ctlv2_coolingflowtempdesiredmax_value",
    "number_ctlv3_coolingflowtempdesiredmax_value",
    "hmux0_runstatsimmersionheaterhours_value",
    "hmux0_runstatsimmersionheaterstarts_value",
    "number_bass3_dewpointoffset_value",
    "number_basv3_dewpointoffset_value",
    "number_ctlv2_dewpointoffset_value",
    "number_ctlv3_dewpointoffset_value",
)

# Timing & Hydration Constants
# Note: Physical eBUS runs at 2400 baud (~240 bytes/s). The delays below ensure reliable
# bus arbitration, avoiding collision storms with physical wall controls (MiPro Sense).
INITIAL_HYDRATION_WAIT_SECONDS = 5.0
HYDRATION_STEP_DELAY_SECONDS = 0.8
SET_CONFIRMATION_DELAY_SECONDS = 1.5
TCP_WRITE_MAX_ATTEMPTS: int = 3
TCP_WRITE_RETRY_DELAYS: tuple[float, ...] = (0.6, 1.2)
TCP_WRITE_TIMEOUT_SECONDS: float = 5.0
TRANSIENT_EBUS_WRITE_ERRORS: tuple[str, ...] = (
    "read timeout",
    "syn received",
    "wrong symbol",
    "arbitration lost",
    "no signal",
    "crc error",
    "ack error",
    "collision",
    "bus error",
    "not ready",
)
HEATING_VETO_SFMODE_FRESHNESS_SECONDS = 15.0
DHW_BOOST_MAX_TIMEOUT_SECONDS = 3600  # 60 minutes safety timeout
ELECTRIC_POWER_STALE_TIMEOUT_SECONDS: float = (
    180.0  # 3 minutes staleness fallback threshold
)
ELECTRIC_POWER_UNAVAILABLE_TIMEOUT_SECONDS: float = (
    600.0  # 10 minutes max age before marking unavailable
)

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
SERVICE_SET_LEGIONELLA_PROTECTION = "set_legionella_protection"
SERVICE_SET_HOLIDAY_MODE = "set_holiday_mode"
SERVICE_CANCEL_HOLIDAY_MODE = "cancel_holiday_mode"
SERVICE_QUICK_VETO = "quick_veto"
SERVICE_CANCEL_QUICK_VETO = "cancel_quick_veto"
SERVICE_START_VENTILATION_BOOST = "start_ventilation_boost"
SERVICE_CANCEL_VENTILATION_BOOST = "cancel_ventilation_boost"
SERVICE_DUMP_MQTT_VALUES = "dump_mqtt_values"
SERVICE_RECORD_TOPIC_CHANGES = "record_topic_changes"
SERVICE_SEND_HEX_COMMAND = "send_hex_command"
SERVICE_READ_PARAMETER = "read_parameter"
SERVICE_WRITE_PARAMETER = "write_parameter"
SERVICE_READ_TIME_PROGRAM = "read_time_program"
SERVICE_WRITE_TIME_PROGRAM = "write_time_program"

DEFAULT_QUICK_VETO_DURATION = 3.0
DEFAULT_QUICK_VETO_BOOST_DELTA = 3.0
DEFAULT_COOLING_QUICK_VETO_BOOST_DELTA = 2.0

# Presets
PRESET_COMFORT = "comfort"
PRESET_MANUAL = "manual"
PRESET_ECO = "eco"
PRESET_BOOST = "boost"
PRESET_AWAY = "away"
PRESET_VENTILATION = "ventilation"
VENTILATION_BOOST_DURATION_MINUTES = 30

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
    "silent": "SilentTimer",
}

# Essential eBUSd messages for Initial Staggered Hydration and No-MiGo Fallback Polling (/get queue)
# Includes controller live modes/states, DHW/climate setpoints, energy counters, and core telemetry
# so both clean startups without retained MQTT payloads and setups with has_migo_link=False stay in sync.
ESSENTIAL_HYDRATION_MESSAGES: list[tuple[str, str]] = [
    # Climate Controller (15.bass3) - Live operational modes, states & Zone 1 / DHW telemetry
    (CIRCUIT_BASS3, "Z1SFMode"),
    (CIRCUIT_BASS3, "Z1Status"),
    (CIRCUIT_BASS3, "Z1OpMode"),
    (CIRCUIT_BASS3, "Z1OpModeCooling"),
    (CIRCUIT_BASS3, "Z1RoomTemp"),
    (CIRCUIT_BASS3, "Z1ActualRoomTempDesired"),
    (CIRCUIT_BASS3, "Z1CoolingTempDesired"),
    (CIRCUIT_BASS3, "Z1CoolingTemp"),
    (CIRCUIT_BASS3, "Z1HeatingState"),
    (CIRCUIT_BASS3, "SystemOperatingState"),
    (CIRCUIT_BASS3, "HwcOpMode"),
    (CIRCUIT_BASS3, "HwcTempDesired"),
    (CIRCUIT_BASS3, "HwcStatus"),
    (CIRCUIT_BASS3, "HwcStorageTemp"),
    (CIRCUIT_BASS3, "HwcLegionellaDay"),
    (CIRCUIT_BASS3, "HwcLegionellaTime"),
    (CIRCUIT_BASS3, "DisplayedOutsideTemp"),
    (CIRCUIT_BASS3, "OutsideTempAvg"),
    (CIRCUIT_BASS3, "WaterPressure"),
    (CIRCUIT_BASS3, "HydraulicScheme"),
    (CIRCUIT_BASS3, "Hc1FlowTemp"),
    (CIRCUIT_BASS3, "Hc1ActualFlowTempDesired"),
    (CIRCUIT_BASS3, "Currenterror"),
    (CIRCUIT_BASS3, "Hc1PumpStatus"),
    # Climate Controller (15.bass3) - Actively readable setpoints, offsets & energy counters (r / r9)
    (CIRCUIT_BASS3, "Z1ManualTemp"),
    (CIRCUIT_BASS3, "Z1CoolingManualTemp"),
    (CIRCUIT_BASS3, "Z1NightTemp"),
    (CIRCUIT_BASS3, "Z1QuickVetoTemp"),
    (CIRCUIT_BASS3, "Z1QuickVetoDuration"),
    (CIRCUIT_BASS3, "Z1QuickVetoEndTime"),
    (CIRCUIT_BASS3, "Z1QuickVetoEndDate"),
    (CIRCUIT_BASS3, "Z1TimeSlotActive"),
    (CIRCUIT_BASS3, "Z1CoolingTimeSlotActive"),
    (CIRCUIT_BASS3, "HolidayTemp"),
    (CIRCUIT_BASS3, "HolidayStartDate"),
    (CIRCUIT_BASS3, "HolidayStartTime"),
    (CIRCUIT_BASS3, "HolidayEndDate"),
    (CIRCUIT_BASS3, "HolidayEndTime"),
    (CIRCUIT_BASS3, "CoolingStartDate"),
    (CIRCUIT_BASS3, "CoolingEndDate"),
    (
        CIRCUIT_BASS3,
        "Z1HolidayTemp",
    ),  # Probes for legacy pre-v1.2.4 CSV compatibility check
    (
        CIRCUIT_BASS3,
        "Z1DayTemp",
    ),  # Probes for legacy pre-v1.3.0 CSV compatibility check (replaced by Z1CoolingManualTemp)
    (CIRCUIT_BASS3, "Z1Timer_Slots"),
    (CIRCUIT_BASS3, "HwcTimer_Slots"),
    (CIRCUIT_BASS3, "CoolingTimer_Slots"),
    (CIRCUIT_BASS3, "CirculationTimer_Slots"),
    (
        CIRCUIT_BASS3,
        "SilentTimer_Slots",
    ),  # Probes for modern v1.3.0+ weekly schedule timer support
    (
        CIRCUIT_BASS3,
        "VentilationBoost",
    ),  # Probes for intensive ventilation boost (30 min heating pause) support
    (CIRCUIT_BASS3, "CoolingReleaseStatus"),
    (CIRCUIT_BASS3, "HwcSFMode"),
    (CIRCUIT_BASS3, "HwcFlowTemp"),
    (CIRCUIT_BASS3, "Hc1HeatCurve"),
    (CIRCUIT_BASS3, "Hc1ExcessTemp"),
    (CIRCUIT_BASS3, "Hc1MinFlowTempDesired"),
    (CIRCUIT_BASS3, "Hc1MaxFlowTempDesired"),
    (CIRCUIT_BASS3, "Hc1SummerTempLimit"),
    (CIRCUIT_BASS3, "CoolingFlowTempDesiredMin"),
    (CIRCUIT_BASS3, "EmergencyFlowTempDesired"),
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
    (CIRCUIT_BASS3, "Z1RoomHumidity"),
    (CIRCUIT_BASS3, "MaxRoomHumidity"),
    (CIRCUIT_BASS3, "BivalencePointHc"),
    (CIRCUIT_BASS3, "BivalencePointHwc"),
    (CIRCUIT_BASS3, "AlternativePoint"),
    (CIRCUIT_BASS3, "CoolingOutsideTempThreshold"),
    (CIRCUIT_BASS3, "DewPointMonitoring"),
    (CIRCUIT_BASS3, "Hc1CoolingEnabled"),
    (CIRCUIT_BASS3, "Hc1DewPointOffset"),
    (CIRCUIT_BASS3, "OffsetOutsideTemp"),
    (CIRCUIT_BASS3, "ContinuosHeating"),
    (CIRCUIT_BASS3, "FrostOverRideTime"),
    (CIRCUIT_BASS3, "MultiRelaySetting"),
    (CIRCUIT_BASS3, "MaintenanceDue"),
    (CIRCUIT_BASS3, "Hc1CircuitType"),
    (CIRCUIT_BASS3, "Hc1MixerMovement"),
    (CIRCUIT_BASS3, "Hc1HeatCurveAdaption"),
    (CIRCUIT_BASS3, "AppSessionStatus"),
    (CIRCUIT_BASS3, "PrEnergySumHcThisMonth"),
    (CIRCUIT_BASS3, "PrEnergySumHcLastMonth"),
    (CIRCUIT_BASS3, "PrEnergySumHc"),
    (CIRCUIT_BASS3, "PrEnergySumHwcThisMonth"),
    (CIRCUIT_BASS3, "PrEnergySumHwcLastMonth"),
    (CIRCUIT_BASS3, "PrEnergySumHwc"),
    # Outdoor Unit (08.hmux0) - Active live telemetry & energy counters (r / r1..r9)
    (CIRCUIT_HMUX0, "HMUStatusCode"),
    (CIRCUIT_HMUX0, "StateCompressor"),
    (CIRCUIT_HMUX0, "Currenterror"),
    (CIRCUIT_HMUX0, "PowerStatus"),
    (CIRCUIT_HMUX0, "RunDataElectricPowerConsumption"),
    (CIRCUIT_HMUX0, "CompressorSilentOperationLevel"),
    (CIRCUIT_HMUX0, "RunDataCompressorSpeed"),
    (CIRCUIT_HMUX0, "RunDataFan1Speed"),
    (CIRCUIT_HMUX0, "RunDataFan2Speed"),
    (CIRCUIT_HMUX0, "RunDataFlowRate"),
    (CIRCUIT_HMUX0, "RunDataBuildingCPumpPower"),
    (CIRCUIT_HMUX0, "RunDataHighPressure"),
    (CIRCUIT_HMUX0, "RunDataFlowTemp"),
    (CIRCUIT_HMUX0, "RunDataReturnTemp"),
    (CIRCUIT_HMUX0, "RunDataFlowTempDesired"),
    (CIRCUIT_HMUX0, "RunDataHeatOutput"),
    (CIRCUIT_HMUX0, "RunDataEnergyIntegral"),
    (CIRCUIT_HMUX0, "RunDataAirInletTemp"),
    (CIRCUIT_HMUX0, "RunDataCompressorInletTemp"),
    (CIRCUIT_HMUX0, "RunDataCompressorOutletTemp"),
    (CIRCUIT_HMUX0, "RunDataEEVOutletTemp"),
    (CIRCUIT_HMUX0, "RunDataCondenserOutTemp"),
    (CIRCUIT_HMUX0, "RunDataCondensationTemp"),
    (CIRCUIT_HMUX0, "RunDataCondensateTemp"),
    (CIRCUIT_HMUX0, "RunDataEvaporationTemp"),
    (CIRCUIT_HMUX0, "RunDataSuperheat"),
    (CIRCUIT_HMUX0, "RunDataEEVPositionAbs"),
    (CIRCUIT_HMUX0, "RunStatsHMUHours"),
    (CIRCUIT_HMUX0, "RunStatsHcHours"),
    (CIRCUIT_HMUX0, "RunStatsAuxHeaterSwitches"),
    (CIRCUIT_HMUX0, "RunStatsHwcHours"),
    (CIRCUIT_HMUX0, "RunStatsHwcStarts"),
    (CIRCUIT_HMUX0, "RunStatsCompressorHours"),
    (CIRCUIT_HMUX0, "RunStatsCompressorStarts"),
    (CIRCUIT_HMUX0, "RunStatsBuildingPumpHours"),
    (CIRCUIT_HMUX0, "RunStatsBuildingCPumpStarts"),
    (CIRCUIT_HMUX0, "RunStats4PortValveHours"),
    (CIRCUIT_HMUX0, "RunStats4PortValveSwitches"),
    (CIRCUIT_HMUX0, "RunStatsFan1Hours"),
    (CIRCUIT_HMUX0, "RunStatsFan1Starts"),
    (CIRCUIT_HMUX0, "RunStatsFan2Hours"),
    (CIRCUIT_HMUX0, "RunStatsFan2Starts"),
    (CIRCUIT_HMUX0, "RunStatsDeiceHours"),
    (CIRCUIT_HMUX0, "RunStatsDeiceStarts"),
    (CIRCUIT_HMUX0, "RunStatsCompressorHc"),
    (CIRCUIT_HMUX0, "RunStatsCompressorHwc"),
    (CIRCUIT_HMUX0, "RunStatsCompressorCool"),
    (CIRCUIT_HMUX0, "PrEnergyElectricHc"),
    (CIRCUIT_HMUX0, "PrEnergyElectricHwc"),
    (CIRCUIT_HMUX0, "PrEnergyElectricCool"),
    (CIRCUIT_HMUX0, "PrEnergyThermalHc"),
    (CIRCUIT_HMUX0, "PrEnergyThermalHwc"),
    (CIRCUIT_HMUX0, "PrEnergyThermalCool"),
    (CIRCUIT_HMUX0, "PrEnergyEnvYieldHc"),
    (CIRCUIT_HMUX0, "PrEnergyEnvYieldHwc"),
    (CIRCUIT_HMUX0, "PrEnergyEnvYieldCool"),
    # Hydraulic Interface (76.vwzio) - Active power, stats & energy counters (r)
    (CIRCUIT_VWZIO, "Currenterror"),
    (CIRCUIT_VWZIO, "PowerStatus"),
    (CIRCUIT_VWZIO, "RunStatsAuxHeaterSwitches"),
    (CIRCUIT_VWZIO, "RunStatsHwcStarts"),
    (CIRCUIT_VWZIO, "RunDataHeaterFlowTemp"),
    (CIRCUIT_VWZIO, "RunStatsHeaterEnergy"),
    (CIRCUIT_VWZIO, "RunStatsHeaterHc"),
    (CIRCUIT_VWZIO, "RunStatsHeaterHwc"),
    (CIRCUIT_VWZIO, "PrEnergyElectricHc"),
    (CIRCUIT_VWZIO, "PrEnergyElectricHwc"),
    (CIRCUIT_VWZIO, "PrEnergyThermalHc"),
    (CIRCUIT_VWZIO, "PrEnergyThermalHwc"),
]

# No-MiGo Fallback Polling Tiers (mimicking MiGo Link fast operational vs hourly slow sync)
FALLBACK_SLOW_POLL_INTERVAL_SECONDS: int = 3600

# On-demand polling interval for user-enabled optional controller energy/yield counters (6 hours)
OPTIONAL_ENERGY_POLL_INTERVAL_SECONDS: int = 21600

# Disabled-by-default controller energy/yield registers polled on demand (startup/enable + every 6h)
# ONLY while the corresponding Home Assistant sensor entity is enabled.
OPTIONAL_CONTROLLER_ENERGY_MESSAGES: frozenset[str] = frozenset(
    {
        "YieldTotal",
        "YieldThisMonth",
        "YieldLastMonth",
        "YieldThisYear",
        "YieldLastYear",
        "PrEnergySumHcThisYear",
        "PrEnergySumHcLastYear",
        "PrEnergySumHwcThisYear",
        "PrEnergySumHwcLastYear",
        "PrEnergySumCooling",
        "PrEnergySumTotal",
        "PrEnergySumTotalThisMonth",
        "PrEnergySumTotalLastMonth",
        "PrEnergySumTotalThisYear",
        "PrEnergySumTotalLastYear",
        "SolarYieldTotal",
    }
)

FALLBACK_FAST_BASS3_MESSAGES: list[tuple[str, str]] = [
    (CIRCUIT_BASS3, "Z1SFMode"),
    (CIRCUIT_BASS3, "Z1Status"),
    (CIRCUIT_BASS3, "Z1OpMode"),
    (CIRCUIT_BASS3, "Z1OpModeCooling"),
    (CIRCUIT_BASS3, "Z1RoomTemp"),
    (CIRCUIT_BASS3, "Z1RoomHumidity"),
    (CIRCUIT_BASS3, "Z1ActualRoomTempDesired"),
    (CIRCUIT_BASS3, "Z1ManualTemp"),
    (CIRCUIT_BASS3, "Z1CoolingTempDesired"),
    (CIRCUIT_BASS3, "Z1CoolingManualTemp"),
    (CIRCUIT_BASS3, "Z1CoolingTemp"),
    (CIRCUIT_BASS3, "Z1NightTemp"),
    (CIRCUIT_BASS3, "Z1QuickVetoTemp"),
    (CIRCUIT_BASS3, "Z1QuickVetoDuration"),
    (CIRCUIT_BASS3, "Z1HeatingState"),
    (CIRCUIT_BASS3, "Z1TimeSlotActive"),
    (CIRCUIT_BASS3, "Z1CoolingTimeSlotActive"),
    (CIRCUIT_BASS3, "SystemOperatingState"),
    (CIRCUIT_BASS3, "HwcOpMode"),
    (CIRCUIT_BASS3, "HwcSFMode"),
    (CIRCUIT_BASS3, "HwcTempDesired"),
    (CIRCUIT_BASS3, "HwcStatus"),
    (CIRCUIT_BASS3, "HwcStorageTemp"),
    (CIRCUIT_BASS3, "HwcFlowTemp"),
    (CIRCUIT_BASS3, "DisplayedOutsideTemp"),
    (CIRCUIT_BASS3, "OutsideTempAvg"),
    (CIRCUIT_BASS3, "WaterPressure"),
    (CIRCUIT_BASS3, "Hc1FlowTemp"),
    (CIRCUIT_BASS3, "Hc1ActualFlowTempDesired"),
    (CIRCUIT_BASS3, "CoolingReleaseStatus"),
    (CIRCUIT_BASS3, "Currenterror"),
    (CIRCUIT_BASS3, "Hc1PumpStatus"),
]

_FALLBACK_FAST_BASS3_SET: frozenset[str] = frozenset(
    m for _c, m in FALLBACK_FAST_BASS3_MESSAGES
)
_STARTUP_ONLY_PROBE_MESSAGES: frozenset[str] = frozenset({"Z1HolidayTemp", "Z1DayTemp"})

FALLBACK_SLOW_BASS3_MESSAGES: list[tuple[str, str]] = [
    (CIRCUIT_BASS3, m)
    for c, m in ESSENTIAL_HYDRATION_MESSAGES
    if c == CIRCUIT_BASS3
    and m not in _FALLBACK_FAST_BASS3_SET
    and m not in _STARTUP_ONLY_PROBE_MESSAGES
]

FALLBACK_SLOW_OUTDOOR_COMMON_MESSAGES: tuple[str, ...] = (
    "Currenterror",
    "CompressorSilentOperationLevel",
    "RunDataFan2Speed",
    "RunDataEEVPositionAbs",
    "RunDataCondenserOutTemp",
    "RunStatsHMUHours",
    "RunStatsHcHours",
    "RunStatsAuxHeaterSwitches",
    "RunStatsHwcHours",
    "RunStatsHwcStarts",
    "RunStatsCompressorHours",
    "RunStatsCompressorStarts",
    "RunStatsBuildingPumpHours",
    "RunStatsBuildingCPumpStarts",
    "RunStats4PortValveHours",
    "RunStats4PortValveSwitches",
    "RunStatsFan1Hours",
    "RunStatsFan1Starts",
    "RunStatsFan2Hours",
    "RunStatsFan2Starts",
    "RunStatsDeiceHours",
    "RunStatsDeiceStarts",
    "RunStatsCompressorHc",
    "RunStatsCompressorHwc",
    "RunStatsCompressorCool",
)

FALLBACK_SLOW_VWZIO_MESSAGES: list[tuple[str, str]] = [
    (CIRCUIT_VWZIO, "Currenterror"),
    (CIRCUIT_VWZIO, "RunStatsAuxHeaterSwitches"),
    (CIRCUIT_VWZIO, "RunStatsHwcStarts"),
    (CIRCUIT_VWZIO, "RunDataHeaterFlowTemp"),
    (CIRCUIT_VWZIO, "RunStatsHeaterEnergy"),
    (CIRCUIT_VWZIO, "RunStatsHeaterHc"),
    (CIRCUIT_VWZIO, "RunStatsHeaterHwc"),
]

# Communication silence timeout before marking eBUS as non-operational (seconds)
EBUSD_TRAFFIC_TIMEOUT_SECONDS: int = 600

# Messages exclusive to Monobloc units (08.hmux0.csv b516 EEPROM table) that do not exist on Split (08.hmu.HW5103.csv)
HMUX0_EXCLUSIVE_MESSAGES: frozenset[str] = frozenset(
    {
        "RunDataCondenserOutTemp",
        "RunStatsAuxHeaterSwitches",
        "RunStatsHwcStarts",
        "RunStatsCompressorHc",
        "RunStatsCompressorHwc",
        "RunStatsCompressorCool",
        "PrEnergyElectricHc",
        "PrEnergyElectricHwc",
        "PrEnergyElectricCool",
        "PrEnergyThermalHc",
        "PrEnergyThermalHwc",
        "PrEnergyThermalCool",
        "PrEnergyEnvYieldHc",
        "PrEnergyEnvYieldHwc",
        "PrEnergyEnvYieldCool",
    }
)

# Unique ID suffixes of outdoor per-mode electrical sensors exclusive to HMUX0 b516 EEPROM
HMUX0_ONLY_SENSOR_UNIQUE_ID_SUFFIXES: frozenset[str] = frozenset(
    {
        "hmux0_prenergyelectriccool_energy",
        "hmux0_prenergyelectrichc_energy",
        "hmux0_prenergyelectrichwc_energy",
    }
)

# Minimum HMU firmware SW version required by [id_sw>=902] for FlowPressure in 08.hmu*.csv
HMU_FLOW_PRESSURE_MIN_SW = 902

# Additional eBUSd messages for Vaillant HMU00 (HW=5103) outdoor units
HMU_HW5103_HYDRATION_MESSAGES: list[tuple[str, str]] = [
    (CIRCUIT_HMU, "FlowPressure"),
    (CIRCUIT_HMU, "YieldHc"),
    (CIRCUIT_HMU, "YieldHwc"),
    (CIRCUIT_HMU, "YieldCooling"),
    (CIRCUIT_HMU, "CopHc"),
    (CIRCUIT_HMU, "CopHwc"),
    (CIRCUIT_HMU, "CopCooling"),
    (CIRCUIT_HMU, "TotalEnergyUsage"),
    (CIRCUIT_HMU, "EnergyIntegral"),
    (CIRCUIT_HMU, "CompressorSilentOperationLevel"),
    (CIRCUIT_HMU, "CompressorHours"),
    (CIRCUIT_HMU, "CompressorStarts"),
    (CIRCUIT_HMU, "CompressorHc"),
    (CIRCUIT_HMU, "CompressorHwc"),
    (CIRCUIT_HMU, "CompressorCool"),
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

# Subset of HMUStatusCode values representing genuine outdoor faults or protective shutdowns
# (S.252..S.590; excludes normal ambient throttling such as fan wind load or current limitation)
HMU_FAULT_STATUS_CODES: frozenset[str] = frozenset(
    {
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
        "high_pressure_switch_open",
        "compressor_outlet_temp_too_high_1",
        "evaporation_temp_too_low",
        "condensation_temp_too_low",
        "evaporation_temp_too_high",
        "condensation_temp_too_high",
        "building_circuit_return_temp_too_low",
        "building_circuit_return_temp_too_high",
        "immersion_heater_flow_temp_too_high",
        "frequency_converter_fault",
        "connection_fault_frequency_converter",
        "four_port_valve_position_fault",
    }
)

# Safe hydraulic water pressure bounds (bar) for aggregated system_health_alert
WATER_PRESSURE_LOW_BAR: float = 0.8
WATER_PRESSURE_HIGH_BAR: float = 2.8

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
    "venting",
]

VWZIO_SECONDARY_HWC_OPTIONS: list[str] = [
    "standby",
    "dhw",
]

HC1_CIRCUIT_TYPE_OPTIONS: list[str] = [
    "inactive",
    "mixer",
    "fixed",
    "hwc",
    "returnincr",
    "pool",
]

MULTI_RELAY_SETTING_OPTIONS: list[str] = [
    "circulation",
    "dryer",
    "zone",
    "legiopump",
]

# Home Assistant Repairs (issue_registry) Identifiers
ISSUE_OUTDATED_HMUX0_CSV = "outdated_hmux0_csv"
ISSUE_OUTDATED_HMU_CSV = "outdated_hmu_csv"
ISSUE_OUTDATED_CONTROLLER_CSV = "outdated_controller_csv"
ISSUE_OUTDATED_VWZIO_CSV = "outdated_vwzio_csv"
ISSUE_MISSING_CUSTOM_CSV = "missing_custom_csv"
CSV_REPAIR_ISSUES: frozenset[str] = frozenset(
    {
        ISSUE_OUTDATED_HMUX0_CSV,
        ISSUE_OUTDATED_HMU_CSV,
        ISSUE_OUTDATED_CONTROLLER_CSV,
        ISSUE_OUTDATED_VWZIO_CSV,
        ISSUE_MISSING_CUSTOM_CSV,
    }
)
CSV_INSTALL_ONE_LINER = (
    "curl -fsSL https://raw.githubusercontent.com/R91g/arotherm-genia-ebusd/"
    "main/scripts/install_ebusd_csvs.sh | sh"
)
ISSUE_NO_EBUSD_MQTT_TRAFFIC = "no_ebusd_mqtt_traffic"
ISSUE_MQTTJSON_NOT_ENABLED = "mqttjson_not_enabled"
ISSUE_EBUSD_SLOW_POLLING_SEED = "ebusd_slow_polling_seed"
ISSUE_EBUSD_EXTERNAL_SWEEP = "ebusd_external_sweep"

SLOW_POLLING_WARNING_THRESHOLD_SECONDS: float = (
    300.0  # 5 minutes without r1 power updates
)
EXTERNAL_SWEEP_CANARY_THRESHOLD: int = 3
EXTERNAL_SWEEP_MIN_REPEATS_PER_CANARY: int = 2
EXTERNAL_SWEEP_MIN_REPEAT_INTERVAL_SECONDS: float = 60.0
EXTERNAL_SWEEP_CLEAR_SECONDS: float = 2400.0
EXTERNAL_SWEEP_SELF_GET_GRACE_SECONDS: float = 30.0

# Registers defined as plain r;u (poll priority 0) that our integration never queries
# and native bus masters (0x10 / 0xf1) never emit passively. Receiving several of them
# via non-retained MQTT indicates an external sweeper (e.g. seed_mqtt_cfg filter-seen=5).
EXTERNAL_SWEEP_CANARY_MESSAGES: frozenset[str] = frozenset(
    {
        "yieldhcday",
        "yieldcoolday",
        "yieldhwcday",
        "yieldhcmonth",
        "yieldhwcmonth",
        "yieldcoolingmonth",
        "supplytempweighted",
        "status16",
        "yieldtotal",
        "hc1status",
        "z1valvestatus",
    }
)

# Signature messages proving our custom 08.hmux0.csv is loaded in ebusd
HMUX0_CUSTOM_SIGNATURE_MESSAGES: tuple[str, ...] = (
    "RunDataFlowTemp",
    "RunDataReturnTemp",
    "RunDataElectricPowerConsumption",
    "StateCompressor",
    "HMUStatusCode",
    "PrEnergyElectricHc",
)

# Message names only present in default upstream ebusd.eu hmu.inc / 08.hmu.csv
UPSTREAM_DEFAULT_CSV_MESSAGES: frozenset[str] = frozenset(
    {
        "waterthroughput",
        "currentconsumedpower",
        "currentyieldpower",
    }
)

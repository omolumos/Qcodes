from functools import partial
from typing import Any, Callable, TypeVar, Union

from qcodes.instrument import VisaInstrument
from qcodes.validators import Bool, Enum, Ints, MultiType, Numbers

from qcodes.parameters import create_on_off_val_mapping

T = TypeVar("T")


def _parse_output_string(string_value: str) -> str:
    """Parses and cleans string output of the multimeter. Removes the surrounding
        whitespace, newline characters and quotes from the parsed data. Some results
        are converted for readablitity (e.g. mov changes to moving).

    Args:
        string_value: The data returned from the multimeter reading commands.

    Returns:
        The cleaned-up output of the multimeter.
    """
    s = string_value.strip().lower()
    if (s[0] == s[-1]) and s.startswith(("'", '"')):
        s = s[1:-1]

    conversions = {"mov": "moving", "rep": "repeat"}
    if s in conversions.keys():
        s = conversions[s]
    return s

def parse_current_from_response(response: str) -> float:
    """
    Extracts a floating-point value in scientific notation from a delimited string.

    Args:
        response: The response string from the instrument.

    Returns:
        The extracted float value.
    """
    # Split the response by commas
    parts = response.split(",")
    try:
        # Extract the desired part and convert it to float
        value_str = parts[0].strip().rstrip("NADC")  # Remove any suffix like 'NADC'
        return float(value_str)
    except (IndexError, ValueError) as e:
        raise ValueError(f"Unable to parse current value from response: {response}") from e


def _parse_output_bool(numeric_value: Union[float, str]) -> bool:
    """Parses and converts the value to boolean type. True is 1.

    Args:
        numeric_value: The numerical value to convert.

    Returns:
        The boolean representation of the numeric value.
    """
    return bool(numeric_value)


class Keithley6517ACommandSetError(Exception):
    pass


class Keithley6517A(VisaInstrument):
    def __init__(
        self, name: str, address: str, check_lang: bool = False, reset_device: bool = False, **kwargs: Any
    ):
        """Driver for the Keithley 6517A multimeter. Based on the Keithley 2000 driver,
            commands have been adapted for the Keithley 6500. This driver does not contain
            all commands available, but only the ones most commonly used.

            Status: beta-version.

        Args:
            name (str): The name used internally by QCoDeS in the DataSet.
            address (str): The VISA device address.
            reset_device (bool): Reset the device on startup if true.
        """
        super().__init__(name, address, terminator="\n", **kwargs)

        if check_lang:
            command_set = self.ask("*LANG?")
            if command_set != "SCPI":
                error_msg = (
                    "This driver only compatible with the 'SCPI' command "
                    f"set, not '{command_set}' set"
                )
                raise Keithley6517ACommandSetError(error_msg)
            command_set = "SCPI"

        self._trigger_sent = False

        self._mode_map = {
            "ac current": '"CURR:AC"',
            "dc current": '"CURR:DC"',
            "ac voltage": '"VOLT:AC"',
            "dc voltage": '"VOLT:DC"',
            "2w resistance": '"RES"',
            "4w resistance": '"FRES"',
            "temperature": '"TEMP"',
            "frequency": '"FREQ"',
        }

        self.add_parameter(
            "mode",
            get_cmd="SENS:FUNC?",
            set_cmd=r'SENS:FUNC {}',
            val_mapping=self._mode_map,
        )

        self.add_parameter(
            "nplc",
            get_cmd=partial(self._get_mode_param, "NPLC", float),
            set_cmd=partial(self._set_mode_param, "NPLC"),
            vals=Numbers(min_value=0.01, max_value=10),
        )

        #  TODO: validator, this one is more difficult since different modes
        #  require different validation ranges.
        self.add_parameter(
            "range",
            get_cmd=partial(self._get_mode_param, "RANG", float),
            set_cmd=partial(self._set_mode_param, "RANG"),
            vals=Numbers(),
        )

        self.add_parameter(
            "auto_range_enabled",
            get_cmd=partial(self._get_mode_param, "RANG:AUTO", _parse_output_bool),
            set_cmd=partial(self._set_mode_param, "RANG:AUTO"),
            vals=Bool(),
        )

        self.add_parameter(
            "averaging_type",
            get_cmd=partial(self._get_mode_param, "AVER:TCON", _parse_output_string),
            set_cmd=partial(self._set_mode_param, "AVER:TCON"),
            vals=Enum("moving", "repeat"),
        )

        self.add_parameter(
            "averaging_count",
            get_cmd=partial(self._get_mode_param, "AVER:COUN", int),
            set_cmd=partial(self._set_mode_param, "AVER:COUN"),
            vals=Ints(min_value=1, max_value=100),
        )

        self.add_parameter(
            "averaging_enabled",
            get_cmd=partial(self._get_mode_param, "AVER:STAT", _parse_output_bool),
            set_cmd=partial(self._set_mode_param, "AVER:STAT"),
            vals=Bool(),
        )

        self.add_parameter(
            "output",
            get_cmd="outp?",
            get_parser=float,
            set_cmd=f"outp {{:d}}",
            val_mapping=create_on_off_val_mapping(on_val=1, off_val=0),
        )

        self.add_parameter(
            "volt",
            get_cmd="sour:volt:lev?",
            get_parser=float,
            set_cmd=f"sour:volt:lev {{:f}}",
            unit = 'V',
            label = 'Voltage',
        )

        self.add_parameter(
            "current",
            get_cmd="meas:curr?",      # Command to retrieve current
            get_parser=parse_current_from_response,  # Custom parser to convert to float
            unit = 'A',
            label = 'Ampere',
        )

        if reset_device:
            self.reset()
        self.write("FORM:DATA ASCII")
        self.connect_message()

    def reset(self) -> None:
        """Reset the device"""
        self.write("*RST")

    def _read_next_value(self) -> float:
        return float(self.ask("READ?"))

    def _get_mode_param(self, parameter: str, parser: Callable[[str], T]) -> T:
        """Reads the current mode of the multimeter and ask for the given parameter.

        Args:
            parameter: The asked parameter after getting the current mode.
            parser: A function that parses the input buffer read.

        Returns:
            Any: the parsed ask command. The parser determines the return data-type.
        """
        mode = _parse_output_string(self._mode_map[self.mode()])
        cmd = f"{mode}:{parameter}?"
        return parser(self.ask(cmd))

    def _set_mode_param(self, parameter: str, value: Union[str, float, bool]) -> None:
        """Gets the current mode of the multimeter and sets the given parameter.

        Args:
            parameter: The set parameter after getting the current mode.
            value: Value to set
        """
        if isinstance(value, bool):
            value = int(value)

        mode = _parse_output_string(self._mode_map[self.mode()])
        cmd = f"{mode}:{parameter} {value}"
        self.write(cmd)

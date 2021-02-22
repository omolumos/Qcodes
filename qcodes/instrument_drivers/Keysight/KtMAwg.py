from .KtMAwgDefs import *

import ctypes
from functools import partial
from typing import Dict, Optional, Any

from qcodes import Instrument, InstrumentChannel
from qcodes.utils.helpers import create_on_off_val_mapping


class KtMAWGChannel(InstrumentChannel):
    """
    Represent the three channels of the Keysight KTM Awg driver.
    The channels can be independently controlled and programmed with
    seperate waveforms.
    """

    def __init__(self, parent: 'KtMAwg', name: str, chan: int) -> None:

        # Sanity Check inputs
        if name not in ["ch1", "ch2", "ch3"]:
            raise ValueError(f"Invalid channel: {name}, expecting ch1:ch3")
        if chan not in [1, 2, 3]:
            raise ValueError(f"Invalid channel: {chan}, expecting ch1:ch3")

        super().__init__(parent, name)
        self._channel = ctypes.create_string_buffer(
            f"Channel{chan}".encode("ascii")
        )

        # Used to access waveforms loaded into the driver
        self._awg_handle: Optional[ctypes.c_int32] = None

        self._catch_error = self.root_instrument._catch_error

        self.add_parameter(
            "output_term_config",
            label="Output Terminal Configuration",
            get_cmd=partial(
                self.root_instrument.get_vi_int,
                KTMAWG_ATTR_TERMINAL_CONFIGURATION,
                ch=self._channel
            ),
            set_cmd=partial(
                self.root_instrument.set_vi_int,
                KTMAWG_ATTR_TERMINAL_CONFIGURATION,
                ch=self._channel
            ),
            val_mapping={
                "differential": KTMAWG_VAL_TERMINAL_CONFIGURATION_DIFFERENTIAL,
                "single": KTMAWG_VAL_TERMINAL_CONFIGURATION_SINGLE_ENDED,
            },
        )

        self.add_parameter(
            "operation",
            label="Operating Mode",
            get_cmd=partial(
                self.root_instrument.get_vi_int,
                KTMAWG_ATTR_OPERATION_MODE,
                ch=self._channel
            ),
            set_cmd=partial(
                self.root_instrument.set_vi_int,
                KTMAWG_ATTR_OPERATION_MODE,
                ch=self._channel
            ),
            val_mapping={
                "continuous": KTMAWG_VAL_OPERATE_CONTINUOUS,
                "burst": KTMAWG_VAL_OPERATE_BURST,
            },
        )

        self.add_parameter(
            "output",
            label="Output Enable",
            get_cmd=partial(
                self.root_instrument.get_vi_bool,
                KTMAWG_ATTR_OUTPUT_ENABLED,
                ch=self._channel
            ),
            set_cmd=partial(
                self.root_instrument.set_vi_bool,
                KTMAWG_ATTR_OUTPUT_ENABLED,
                ch=self._channel
            ),
            val_mapping=create_on_off_val_mapping(on_val=1, off_val=0),
        )

        self.add_parameter(
            "gain_config",
            label="AWG Gain Control Mode",
            set_cmd=self._set_gain_control,
            get_cmd=self._get_gain_control,
            val_mapping={
                "composite": KTMAWG_VAL_GAIN_CONTROL_COMPOSITE,
                "component": KTMAWG_VAL_GAIN_CONTROL_COMPONENT,
            },
        )
        self.add_parameter("gain",
                           label="Composite Output Gain",
                           set_cmd=self._set_gain,
                           get_cmd=None)

        self.add_parameter(
            "analog_gain",
            label="Analog Output Gain",
            set_cmd=self._set_analog_gain,
            get_cmd=self._get_analog_gain,
        )

        self.add_parameter(
            "digital_gain",
            label="Digital Output Gain",
            set_cmd=self._set_digital_gain,
            get_cmd=self._get_digital_gain,
        )

    def load_waveform(self, filename: str) -> None:
        path = ctypes.create_string_buffer(filename.encode("ascii"))
        self._awg_handle = ctypes.c_int32(0)
        status = self.root_instrument._dll.\
            KtMAwg_WaveformCreateChannelWaveformFromFile(
                self.root_instrument._session,
                self._channel,
                b"SineWaveform",
                0, path,
                ctypes.byref(self._awg_handle),
            )
        self.root_instrument._catch_error(status)

    def clear_waveform(self) -> None:
        if self._awg_handle is not None:
            status = self.root_instrument._dll.KtMAwg_ClearArbWaveform(
                self.root_instrument._session, self._awg_handle
            )
            self._catch_error(status)
            self._awg_handle = None

    def play_waveform(self) -> None:
        if self._awg_handle is None:
            raise ValueError("Waveform has not been loaded!")

        status = self.root_instrument._dll.KtMAwg_ArbitrarySetHandle(
            self.root_instrument._session, self._channel, self._awg_handle
        )

        self._catch_error(status)

        status = self.root_instrument._dll.KtMAwg_Resolve(
            self.root_instrument._session
        )
        self._catch_error(status)

        status = self.root_instrument._dll.KtMAwg_Apply(
            self.root_instrument._session
        )
        self._catch_error(status)

        status = self.root_instrument._dll.KtMAwg_InitiateGenerationByChannel(
            self.root_instrument._session, self._channel
        )
        self._catch_error(status)

    def stop_waveform(self) -> None:
        status = self.root_instrument._dll.KtMAwg_AbortGenerationByChannel(
            self.root_instrument._session, self._channel
        )
        self._catch_error(status)

    def _set_gain_control(self, val: int) -> None:
        self.root_instrument._dll.KtMAwg_ArbitrarySetGainControl(
            self.root_instrument._session, self._channel, val
        )

    def _get_gain_control(self) -> int:
        res = ctypes.c_int32(0)
        self.root_instrument._dll.KtMAwg_ArbitraryGetGainControl(
            self.root_instrument._session, self._channel, ctypes.byref(res)
        )
        return res.value

    def _set_analog_gain(self, val: float) -> None:
        v = ctypes.c_double(val)
        self.root_instrument._dll.KtMAwg_ArbitrarySetAnalogGain(
            self.root_instrument._session, self._channel, v
        )

    def _get_analog_gain(self) -> float:
        res = ctypes.c_double(0)
        self.root_instrument._dll.KtMAwg_ArbitraryGetAnalogGain(
            self.root_instrument._session, self._channel, ctypes.byref(res)
        )
        return res.value

    def _set_digital_gain(self, val: float) -> None:
        v = ctypes.c_double(val)
        self.root_instrument._dll.KtMAwg_ArbitrarySetDigitalGain(
            self.root_instrument._session, self._channel, v
        )

    def _get_digital_gain(self) -> float:
        res = ctypes.c_double(0)
        self.root_instrument._dll.KtMAwg_ArbitraryGetDigitalGain(
            self.root_instrument._session, self._channel, ctypes.byref(res)
        )
        return res.value

    def _set_gain(self, val: float) -> None:
        v = ctypes.c_double(val)
        self.root_instrument._dll.KtMAwg_ArbitrarySetGain(
            self.root_instrument._session, self._channel, v
        )


class KtMAwg(Instrument):
    """
    AWG Driver for the Keysight M9336A PXIe I/Q Arbitrary Waveform
    Generator. This driver provides a simple wrapper around the
    IVI-C drivers from Keysight. The output configuration, gain
    can be controlled and a waveform can be loaded from a file.
    """
    _default_buf_size = 256

    def __init__(self,
                 name: str,
                 address: str,
                 options: str = "",
                 dll_path: str = r"C:\Program Files\IVI "
                                 r"Foundation\IVI\Bin\KtMAwg_64.dll",
                 **kwargs: Any) -> None:
        super().__init__(name, **kwargs)

        self._address = bytes(address, "ascii")
        self._options = bytes(options, "ascii")
        self._session = ctypes.c_int(0)
        self._dll_loc = dll_path
        self._dll = ctypes.cdll.LoadLibrary(self._dll_loc)
        self._channel = ctypes.create_string_buffer(b"Channel1")

        for ch_num in [1, 2, 3]:
            ch_name = f"ch{ch_num}"
            channel = KtMAWGChannel(
                self,
                ch_name,
                ch_num,
            )
            self.add_submodule(ch_name, channel)

        self.get_driver_desc = partial(
            self.get_vi_string, KTMAWG_ATTR_SPECIFIC_DRIVER_DESCRIPTION
        )
        self.get_driver_prefix = partial(
            self.get_vi_string, KTMAWG_ATTR_SPECIFIC_DRIVER_PREFIX
        )
        self.get_driver_revision = partial(
            self.get_vi_string, KTMAWG_ATTR_SPECIFIC_DRIVER_REVISION
        )
        self.get_firmware_revision = partial(
            self.get_vi_string, KTMAWG_ATTR_INSTRUMENT_FIRMWARE_REVISION
        )
        self.get_model = partial(self.get_vi_string,
                                 KTMAWG_ATTR_INSTRUMENT_MODEL)
        self.get_serial_number = partial(
            self.get_vi_string, KTMAWG_ATTR_MODULE_SERIAL_NUMBER
        )
        self.get_manufactorer = partial(
            self.get_vi_string, KTMAWG_ATTR_INSTRUMENT_MANUFACTURER
        )

        self._connect()

        self.connect_message()

    def _connect(self) -> None:
        status = self._dll.KtMAwg_InitWithOptions(
            self._address, 1, 1, self._options, ctypes.byref(self._session)
        )
        if status:
            raise SystemError(f"connection to device failed! error: {status}")

    def get_idn(self) -> Dict[str, Optional[str]]:
        """generates the ``*IDN`` dictionary for qcodes"""

        id_dict: Dict[str, Optional[str]] = {
            "firmware": self.get_firmware_revision(),
            "model": self.get_model(),
            "serial": self.get_serial_number(),
            "vendor": self.get_manufactorer(),
        }
        return id_dict

    def _catch_error(self, status: int) -> None:
        if status == 0:
            # No error
            return

        err = ctypes.c_int32(0)
        err_msg = ctypes.create_string_buffer(256)

        self._dll.KtMAwg_GetError(self._session,
                                  ctypes.byref(err),
                                  255,
                                  err_msg)

        raise ValueError(f"Got dll error num {err.value}"
                         f"msg {err_msg.value.decode('ascii')}")

    # Query the driver for errors

    def get_errors(self) -> None:
        error_code = ctypes.c_int(-1)
        error_message = ctypes.create_string_buffer(256)
        while error_code.value != 0:
            status = self._dll.KtMAwg_error_query(
                self._session, ctypes.byref(error_code), error_message
            )
            assert status == 0
            print(
                f"error_query: {error_code.value}, "
                f"{error_message.value.decode('utf-8')}"
            )

    # Generic functions for reading/writing different attributes
    def get_vi_string(self, attr: int, ch: bytes = b"") -> str:
        s = ctypes.create_string_buffer(self._default_buf_size)
        status = self._dll.KtMAwg_GetAttributeViString(
            self._session, ch, attr, self._default_buf_size, s
        )
        if status:
            raise ValueError(f"Driver error: {status}")
        return s.value.decode("utf-8")

    def get_vi_bool(self, attr: int, ch: bytes = b"") -> bool:
        s = ctypes.c_uint16(0)
        status = self._dll.KtMAwg_GetAttributeViBoolean(
            self._session, ch, attr, ctypes.byref(s)
        )
        if status:
            raise ValueError(f"Driver error: {status}")
        return bool(s)

    def set_vi_bool(self, attr: int, value: bool, ch: bytes = b"") -> bool:
        v = ctypes.c_uint16(1) if value else ctypes.c_uint16(0)
        status = self._dll.KtMAwg_SetAttributeViBoolean(self._session,
                                                        ch,
                                                        attr,
                                                        v)
        if status:
            raise ValueError(f"Driver error: {status}")
        return True

    def get_vi_real64(self, attr: int, ch: bytes = b"") -> float:
        s = ctypes.c_double(0)
        status = self._dll.KtMAwg_GetAttributeViReal64(
            self._session, ch, attr, ctypes.byref(s)
        )

        if status:
            raise ValueError(f"Driver error: {status}")
        return float(s.value)

    def set_vi_real64(self, attr: int, value: float, ch: bytes = b"") -> bool:
        v = ctypes.c_double(value)
        status = self._dll.KtMAwg_SetAttributeViReal64(self._session,
                                                       ch,
                                                       attr,
                                                       v)
        if status:
            raise ValueError(f"Driver error: {status}")
        return True

    def set_vi_int(self, attr: int, value: int, ch: bytes = b"") -> bool:
        v = ctypes.c_int32(value)
        status = self._dll.KtMAwg_SetAttributeViInt32(self._session,
                                                      ch,
                                                      attr,
                                                      v)
        if status:
            raise ValueError(f"Driver error: {status}")
        return True

    def get_vi_int(self, attr: int, ch: bytes = b"") -> int:
        v = ctypes.c_int32(0)
        status = self._dll.KtMAwg_GetAttributeViInt32(
            self._session, ch, attr, ctypes.byref(v)
        )
        if status:
            raise ValueError(f"Driver error: {status}")
        return int(v.value)

    def close(self) -> None:
        self._dll.KtMAwg_close(self._session)
        super().close()

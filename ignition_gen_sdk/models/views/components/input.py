"""Input palette component models — all 17 ia.input.* types.

Each class:
- Subclasses Component (which subclasses IgnitionBaseModel)
- Overrides model_config with extra="allow"
- Locks type via Literal["ia.input.*"]
- Provides a typed Props sub-model (also extra="allow") for documented props

Props sub-models include documented 8.3 props as Optional fields. Unknown
props the gateway emits pass through extra="allow" without error.

Doc source: https://docs.inductiveautomation.com/docs/8.3/appendix/components/
            perspective-components/perspective-input-palette

Drift notes:
- Designer-exported Button views use: text, style, enabled, primary, image.icon.path
  The `primary` and `image` props are present in exports but not in the
  minimal prop list from docs — both are accepted via extra="allow".
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from ...base import IgnitionBaseModel
from ..component import Component


# ---------------------------------------------------------------------------
# Button
# ---------------------------------------------------------------------------

class ButtonProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    text: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    # fixture drift: `primary` (bool) and `image` (dict) appear in gateway output
    # but are not in the minimal doc prop list; extra="allow" absorbs them.
    action: dict[str, Any] | None = None


class Button(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.button"] = "ia.input.button"
    props: ButtonProps = Field(default_factory=ButtonProps)


# ---------------------------------------------------------------------------
# Checkbox
# ---------------------------------------------------------------------------

class CheckboxProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    selected: bool | None = None
    text: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Checkbox(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.checkbox"] = "ia.input.checkbox"
    props: CheckboxProps = Field(default_factory=CheckboxProps)


# ---------------------------------------------------------------------------
# Dropdown
# ---------------------------------------------------------------------------

class DropdownProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: Any | None = None
    options: list[Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    placeholder: str | None = None


class Dropdown(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.dropdown"] = "ia.input.dropdown"
    props: DropdownProps = Field(default_factory=DropdownProps)


# ---------------------------------------------------------------------------
# Slider
# ---------------------------------------------------------------------------

class SliderProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: float | None = None
    min: float | None = None
    max: float | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    step: float | None = None
    orientation: str | None = None


class Slider(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.slider"] = "ia.input.slider"
    props: SliderProps = Field(default_factory=SliderProps)


# ---------------------------------------------------------------------------
# Text Field
# ---------------------------------------------------------------------------

class TextFieldProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    text: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    # Real IA prop is "placeholder" (verified docs 8.x); "placeholderText" doesn't exist
    placeholder: str | None = None
    deferUpdates: bool | None = None
    readOnly: bool | None = None


class TextField(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.text-field"] = "ia.input.text-field"
    props: TextFieldProps = Field(default_factory=TextFieldProps)


# ---------------------------------------------------------------------------
# Text Area
# ---------------------------------------------------------------------------

class TextAreaProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    text: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    # Real IA prop is "placeholder" (verified docs 8.x); "placeholderText" doesn't exist
    placeholder: str | None = None
    deferUpdates: bool | None = None
    readOnly: bool | None = None


class TextArea(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.text-area"] = "ia.input.text-area"
    props: TextAreaProps = Field(default_factory=TextAreaProps)


# ---------------------------------------------------------------------------
# Numeric Entry Field
# ---------------------------------------------------------------------------

class NumericEntryFieldProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: float | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    min: float | None = None
    max: float | None = None
    format: str | None = None


class NumericEntryField(Component):
    # The REAL 8.3 wire type is "ia.input.numeric-entry-field" — verified
    # against live Designer-authored views. "ia.input.numericEntry" appears in
    # ZERO live views.
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.numeric-entry-field"] = "ia.input.numeric-entry-field"
    props: NumericEntryFieldProps = Field(default_factory=NumericEntryFieldProps)


# ---------------------------------------------------------------------------
# Date Time Input
# ---------------------------------------------------------------------------

class DateTimeInputProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    format: str | None = None


class DateTimeInput(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.date-time-input"] = "ia.input.date-time-input"
    props: DateTimeInputProps = Field(default_factory=DateTimeInputProps)


# ---------------------------------------------------------------------------
# Date Time Picker
# ---------------------------------------------------------------------------

class DateTimePickerProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    format: str | None = None


class DateTimePicker(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.date-time-picker"] = "ia.input.date-time-picker"
    props: DateTimePickerProps = Field(default_factory=DateTimePickerProps)


# ---------------------------------------------------------------------------
# Radio Group
# ---------------------------------------------------------------------------

class RadioGroupProps(IgnitionBaseModel):
    # Verified vs IA 8.x docs (perspective-radio-group): options
    # are declared as `radios[]` of {text, value, selected} — there is NO
    # `options` prop on this component. `value` mirrors the selected radio's
    # value; `index` the selected index; `orientation` is "row"|"column".
    model_config = ConfigDict(extra="allow")
    value: Any | None = None
    index: int | None = None
    radios: list[Any] | None = None
    orientation: str | None = None
    textPosition: str | None = None
    align: str | None = None
    justify: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class RadioGroup(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.radio-group"] = "ia.input.radio-group"
    props: RadioGroupProps = Field(default_factory=RadioGroupProps)


# ---------------------------------------------------------------------------
# Toggle Switch
# ---------------------------------------------------------------------------

class ToggleSwitchProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    selected: bool | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class ToggleSwitch(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.toggle-switch"] = "ia.input.toggle-switch"
    props: ToggleSwitchProps = Field(default_factory=ToggleSwitchProps)


# ---------------------------------------------------------------------------
# Multi-State Button
# ---------------------------------------------------------------------------

class MultiStateButtonProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    state: int | None = None
    states: list[Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class MultiStateButton(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.multi-state-button"] = "ia.input.multi-state-button"
    props: MultiStateButtonProps = Field(default_factory=MultiStateButtonProps)


# ---------------------------------------------------------------------------
# One Shot Button
# ---------------------------------------------------------------------------

class OneShotButtonProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    text: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    action: dict[str, Any] | None = None


class OneShotButton(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.oneshotbutton"] = "ia.input.oneshotbutton"
    props: OneShotButtonProps = Field(default_factory=OneShotButtonProps)


# ---------------------------------------------------------------------------
# Password Field
# ---------------------------------------------------------------------------

class PasswordFieldProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    text: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    placeholder: str | None = None


class PasswordField(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.password-field"] = "ia.input.password-field"
    props: PasswordFieldProps = Field(default_factory=PasswordFieldProps)


# ---------------------------------------------------------------------------
# File Upload
# ---------------------------------------------------------------------------

class FileUploadProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    allowedTypes: list[str] | None = None
    maxSize: int | None = None


class FileUpload(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.fileupload"] = "ia.input.fileupload"
    props: FileUploadProps = Field(default_factory=FileUploadProps)


# ---------------------------------------------------------------------------
# Signature Pad
# ---------------------------------------------------------------------------

class SignaturePadProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class SignaturePad(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.signature-pad"] = "ia.input.signature-pad"
    props: SignaturePadProps = Field(default_factory=SignaturePadProps)


# ---------------------------------------------------------------------------
# Barcode Scanner Input
# ---------------------------------------------------------------------------

class BarcodeScannerInputProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class BarcodeScannerInput(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.input.barcodescannerinput"] = "ia.input.barcodescannerinput"
    props: BarcodeScannerInputProps = Field(default_factory=BarcodeScannerInputProps)

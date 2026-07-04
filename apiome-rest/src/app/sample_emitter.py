"""No-op sample export target — MFX-1.1 (#3834).

The acceptance adapter for the Emitter SPI: a deliberately trivial
:class:`~app.emitter.Emitter` that *registers and appears in the target list* with
**no engine changes** — the whole point of the seam. It is also the smallest
possible worked example of the contract for a format epic to copy.

It is a *no-op*: :meth:`SampleEmitter.emit` returns an empty single-file artifact
with no provenance or losses. The static :class:`~app.emitter.CapabilityProfile`
declares no supported constructs so the fidelity engine (MFX-EPIC-2) can treat every
rich source as lossy against this target.
"""

from __future__ import annotations

from typing import Optional, Union

from pydantic import Field

from .canonical_model import ApiParadigm, CanonicalApi
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmittedFile,
    EmitResult,
    Emitter,
)

__all__ = ["SampleEmitOptions", "SampleEmitter", "SAMPLE_EMIT_FORMAT"]

#: Format key this no-op target registers under.
SAMPLE_EMIT_FORMAT = "sample-noop"


class SampleEmitOptions(EmitOptions):
    """Per-target options for :class:`SampleEmitter` (MFX-1.4)."""

    content: str = Field(
        default="",
        description="Plain-text payload written into the sample artifact.",
    )


class SampleEmitter(Emitter, register=True):
    """A no-op reference emitter demonstrating the Emitter SPI."""

    key = "sample"
    format = SAMPLE_EMIT_FORMAT
    label = "Sample (no-op)"
    description = "A no-op reference emitter that demonstrates the Emitter SPI."
    icon = "flask-conical"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = SampleEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """Declare no supported constructs — every rich export is lossy."""
        return CapabilityProfile()

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[SampleEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Return a single-file artifact without mutating ``api``."""
        _ = api
        options = (
            opts
            if isinstance(opts, SampleEmitOptions)
            else SampleEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        return EmitResult(
            files=[
                EmittedFile(
                    path="sample.txt",
                    content=options.content,
                    media_type="text/plain",
                )
            ],
            media_type="text/plain",
        )

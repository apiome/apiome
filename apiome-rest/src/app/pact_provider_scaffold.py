"""Provider test scaffolding — PFX-8.19 (#7316).

A provider team adopting Pact starts from a blank file and has to find out which provider states
its consumers rely on. :func:`scaffold_provider_test` writes the starting point instead: one
provider verification test in the chosen language, wired to this broker, with one state handler
stub per provider state the provider's pacts name.

==============  ==================  ==============================================================
Language id     Library             File
==============  ==================  ==============================================================
``typescript``  pact-js             ``<provider>.pact.test.ts`` — Jest/Vitest ``Verifier`` test
``java``        pact-jvm (JUnit 5)  ``<Provider>PactTest.java`` — ``@Provider`` / ``@PactBroker``
``go``          pact-go v2          ``<provider>_pact_test.go`` — ``provider.NewVerifier()``
``python``      pact-python 2       ``test_<provider>_pact.py`` — ``Verifier.verify_with_broker``
==============  ==================  ==============================================================

Every file:

* reads the broker from the environment — ``PACT_BROKER_BASE_URL`` and ``PACT_BROKER_TOKEN`` — so
  **no secret is ever written into it**, and the provider's own address from
  ``PROVIDER_BASE_URL`` (default ``http://localhost:8080``);
* selects pacts with the **recommended selectors** (:data:`RECOMMENDED_SELECTORS`: the consumers'
  main branches and whatever is deployed or released) and turns **pending pacts on**;
* publishes results only in CI (``CI=true``), as ``GIT_COMMIT`` on ``GIT_BRANCH``;
* carries one **state handler stub** per state, in name order, and a table of the parameters each
  state was sent with in the pacts (one example value per parameter);
* marks each state the provider has **not registered in Apiome** (PFX-3.3) with a fixed comment,
  because hosted verification cannot set it up yet.

**Safety.** State and provider names come from published pacts, so nobody controls them but the
consumers. They are only ever written as escaped string literals of the target language — never
into a comment, and into an identifier (a Java or Python method name) only after being reduced to
ASCII letters and digits. Example values are written as JSON text inside a string literal (Python:
the ``repr`` of the decoded JSON).

**Nothing is dropped silently.** More than :data:`MAX_STATES` states, or a state name longer than
:data:`MAX_STATE_NAME`, is left out of the file with a ``notice`` saying so.

Pure: no I/O. The states come from :mod:`app.pact_provider_scaffold_service`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "CODE_LANGUAGE_UNSUPPORTED",
    "LANGUAGES",
    "MAX_STATES",
    "MAX_STATE_NAME",
    "NOTICE_NO_PACTS",
    "NOTICE_STATE_LEFT_OUT",
    "NOTICE_STATE_UNREGISTERED",
    "RECOMMENDED_SELECTORS",
    "ProviderScaffold",
    "ScaffoldError",
    "ScaffoldNotice",
    "ScaffoldState",
    "scaffold_provider_test",
]

#: The language is not one of :data:`LANGUAGES`.
CODE_LANGUAGE_UNSUPPORTED = "provider-scaffold-language-unsupported"

#: Notice: the provider has no pact the recommended selectors choose, so the file has no handlers.
NOTICE_NO_PACTS = "provider-scaffold-no-pacts"
#: Notice: a state the pacts name is not registered in Apiome (hosted verification cannot set it up).
NOTICE_STATE_UNREGISTERED = "provider-scaffold-state-unregistered"
#: Notice: a state was left out of the file (too many, or a name too long), with the reason.
NOTICE_STATE_LEFT_OUT = "provider-scaffold-state-left-out"

#: The most state handlers one file carries.
MAX_STATES = 200
#: The longest state name written into a file.
MAX_STATE_NAME = 500

#: The consumer version selectors every scaffold uses: what each consumer has on its main branch,
#: and whatever is deployed or released — Pact's recommended set for a provider build.
RECOMMENDED_SELECTORS: Tuple[Mapping[str, Any], ...] = ({"mainBranch": True}, {"deployedOrReleased": True})

#: What the file reads from the environment, and what for.
ENVIRONMENT = (
    ("PACT_BROKER_BASE_URL", "This workspace's broker base URL."),
    ("PACT_BROKER_TOKEN", "An API key that can read pacts (and publish results in CI)."),
    ("PROVIDER_BASE_URL", "Where the provider under test listens (default http://localhost:8080)."),
    ("GIT_COMMIT", "The provider version results are published as."),
    ("GIT_BRANCH", "The provider branch, for pending pacts."),
    ("CI", "Results are published only when it is true."),
)


@dataclass(frozen=True)
class LanguageInfo:
    """One supported language.

    Attributes:
        label: How people name it (``TypeScript · pact-js``).
        library: The Pact library the file uses.
        dependency: What to install for the file to run.
    """

    label: str
    library: str
    dependency: str


#: Every language a scaffold can be written in.
LANGUAGES: Dict[str, LanguageInfo] = {
    "typescript": LanguageInfo("TypeScript · pact-js", "pact-js", "npm install --save-dev @pact-foundation/pact"),
    "java": LanguageInfo(
        "Java · pact-jvm",
        "pact-jvm",
        "testImplementation 'au.com.dius.pact.provider:junit5:4.6.x' (Gradle) or the Maven equivalent",
    ),
    "go": LanguageInfo("Go · pact-go", "pact-go", "go get github.com/pact-foundation/pact-go/v2"),
    "python": LanguageInfo("Python · pact-python", "pact-python", "pip install 'pact-python>=2,<3' pytest"),
}


class ScaffoldError(ValueError):
    """A request the generator refuses, with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScaffoldState:
    """One provider state the provider's pacts name.

    Attributes:
        name: The state, exactly as the pacts write it.
        params: Each parameter the pacts send with it, with one example value, by name.
        registered: Whether the provider registered it in Apiome (PFX-3.3).
        setup_kind: The registered setup (``state_change`` / ``fixture``), when registered.
        interactions: How many selected interactions name it.
        consumers: The consumers whose pacts name it, by handle.
    """

    name: str
    params: Tuple[Tuple[str, Any], ...] = ()
    registered: bool = False
    setup_kind: Optional[str] = None
    interactions: int = 0
    consumers: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ScaffoldNotice:
    """Something worth knowing about the file: a flagged state, one left out, no pacts.

    Attributes:
        code: One of the ``NOTICE_*`` codes.
        message: What happened, for a person.
        state: The state it is about, when it is about one.
    """

    code: str
    message: str
    state: Optional[str] = None

    def as_json(self) -> Dict[str, Any]:
        """The notice as a response object."""
        out: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.state is not None:
            out["state"] = self.state
        return out


@dataclass
class ProviderScaffold:
    """A written test file.

    Attributes:
        language: The language id.
        file_name: The suggested file name.
        content: The file's text.
        states: The states that have a handler, in file order.
        notices: Every notice.
    """

    language: str
    file_name: str
    content: str
    states: List[ScaffoldState] = field(default_factory=list)
    notices: List[ScaffoldNotice] = field(default_factory=list)


# =============================================================================================
# Literals and names
# =============================================================================================


def _json_text(value: Any) -> str:
    """Compact, key-sorted JSON of a value."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _js_string(text: str) -> str:
    """A TypeScript / Java string literal (JSON escapes are valid in both; ASCII-only output)."""
    return json.dumps(text, ensure_ascii=True)


def _go_string(text: str) -> str:
    """A Go interpreted string literal: printable ASCII kept, everything else escaped."""
    out = ['"']
    for char in text:
        code = ord(char)
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif 0x20 <= code < 0x7F:
            out.append(char)
        elif code <= 0xFFFF:
            out.append(f"\\u{code:04x}")
        else:
            out.append(f"\\U{code:08x}")
    out.append('"')
    return "".join(out)


def _py_literal(value: Any) -> str:
    """A Python literal of a decoded JSON value (``repr`` is exact for str/int/float/bool/None/list/dict)."""
    return repr(json.loads(_json_text(value)))


def _words(text: str) -> List[str]:
    """The ASCII letters-and-digits runs of a text."""
    return re.findall(r"[A-Za-z0-9]+", text)


def _pascal(text: str, fallback: str) -> str:
    """``billing service`` → ``BillingService``; a leading digit gets the fallback in front."""
    name = "".join(word[:1].upper() + word[1:] for word in _words(text)) or fallback
    return name if not name[0].isdigit() else f"{fallback}{name}"


def _identifiers(names: Sequence[str], style: str) -> List[str]:
    """One unique method name per state: ``camel`` (Java) or ``snake`` (Python), ASCII only."""
    used: Dict[str, int] = {}
    out: List[str] = []
    for name in names:
        # A ``given`` prefix keeps every name clear of the language's keywords and of a leading digit.
        words = [word.lower() for word in _words(name)][:12] or ["state"]
        if style == "camel":
            base = "given" + "".join(word[:1].upper() + word[1:] for word in words)
        else:
            base = "given_" + "_".join(words)
        base = base[:80]
        count = used.get(base, 0)
        used[base] = count + 1
        out.append(base if count == 0 else f"{base}{'_' if style == 'snake' else ''}{count + 1}")
    return out


def _file_stem(provider: str) -> str:
    """``Billing Service`` → ``billing-service`` (``provider`` when nothing is left)."""
    return "-".join(word.lower() for word in _words(provider))[:80] or "provider"


def _example_params(state: ScaffoldState) -> Dict[str, Any]:
    """The example parameters of a state, by name."""
    return {name: value for name, value in state.params}


#: The comment above a handler for a state the provider has not registered in Apiome.
_UNREGISTERED = "Not registered in Apiome: hosted verification cannot set this state up yet."

#: The comment inside every handler.
_TODO = "TODO: put the provider into this state (its example parameters are in EXAMPLE_PARAMETERS)."


# =============================================================================================
# The four languages
# =============================================================================================


def _typescript(provider: str, states: Sequence[ScaffoldState]) -> str:
    """A pact-js ``Verifier`` test (Jest or Vitest)."""
    examples = "".join(
        f"  {_js_string(state.name)}: {_js_string(_json_text(_example_params(state)))},\n" for state in states
    )
    handlers = ""
    for state in states:
        if not state.registered:
            handlers += f"      // {_UNREGISTERED}\n"
        handlers += (
            f"      {_js_string(state.name)}: async (params) => {{\n"
            f"        // {_TODO}\n"
            "        void params;\n"
            "      },\n"
        )
    return (
        "// Provider verification for "
        f"{_file_stem(provider)} — generated by Apiome (apiome pact scaffold-provider-tests).\n"
        "// The broker and its token come from the environment; nothing secret is written here.\n"
        "import { Verifier } from '@pact-foundation/pact';\n"
        "\n"
        "/** The parameters each provider state was sent with in the pacts (one example each), as JSON. */\n"
        f"export const EXAMPLE_PARAMETERS: Record<string, string> = {{\n{examples}}};\n"
        "\n"
        "describe('Pact verification', () => {\n"
        "  it('honours the pacts of its consumers', () => {\n"
        "    return new Verifier({\n"
        f"      provider: {_js_string(provider)},\n"
        "      providerBaseUrl: process.env.PROVIDER_BASE_URL ?? 'http://localhost:8080',\n"
        "      pactBrokerUrl: process.env.PACT_BROKER_BASE_URL,\n"
        "      pactBrokerToken: process.env.PACT_BROKER_TOKEN,\n"
        "      consumerVersionSelectors: [{ mainBranch: true }, { deployedOrReleased: true }],\n"
        "      enablePending: true,\n"
        "      publishVerificationResult: process.env.CI === 'true',\n"
        "      providerVersion: process.env.GIT_COMMIT,\n"
        "      providerVersionBranch: process.env.GIT_BRANCH,\n"
        f"      stateHandlers: {{\n{handlers}      }},\n"
        "    }).verifyProvider();\n"
        "  });\n"
        "});\n"
    )


def _java(provider: str, states: Sequence[ScaffoldState]) -> Tuple[str, str]:
    """A pact-jvm JUnit 5 test class, and its class name."""
    class_name = f"{_pascal(provider, 'Provider')[:80]}PactTest"
    entries = ",\n".join(
        f"        Map.entry({_js_string(state.name)}, {_js_string(_json_text(_example_params(state)))})"
        for state in states
    )
    examples = f"Map.ofEntries(\n{entries})" if states else "Map.of()"
    methods = ""
    for state, method in zip(states, _identifiers([state.name for state in states], "camel")):
        if not state.registered:
            methods += f"    // {_UNREGISTERED}\n"
        methods += (
            f"    @State({_js_string(state.name)})\n"
            f"    public void {method}(Map<String, Object> params) {{\n"
            f"        // {_TODO}\n"
            "    }\n\n"
        )
    content = (
        f"// Provider verification for {_file_stem(provider)} — generated by Apiome "
        "(apiome pact scaffold-provider-tests).\n"
        "// The broker and its token come from the environment; nothing secret is written here.\n"
        "import au.com.dius.pact.provider.junit5.HttpTestTarget;\n"
        "import au.com.dius.pact.provider.junit5.PactVerificationContext;\n"
        "import au.com.dius.pact.provider.junit5.PactVerificationInvocationContextProvider;\n"
        "import au.com.dius.pact.provider.junitsupport.Provider;\n"
        "import au.com.dius.pact.provider.junitsupport.State;\n"
        "import au.com.dius.pact.provider.junitsupport.loader.PactBroker;\n"
        "import au.com.dius.pact.provider.junitsupport.loader.PactBrokerAuth;\n"
        "import au.com.dius.pact.provider.junitsupport.loader.PactBrokerConsumerVersionSelectors;\n"
        "import au.com.dius.pact.provider.junitsupport.loader.SelectorBuilder;\n"
        "import java.net.URI;\n"
        "import java.util.Map;\n"
        "import org.junit.jupiter.api.BeforeEach;\n"
        "import org.junit.jupiter.api.TestTemplate;\n"
        "import org.junit.jupiter.api.extension.ExtendWith;\n"
        "\n"
        f"@Provider({_js_string(provider)})\n"
        "@PactBroker(\n"
        '    url = "${PACT_BROKER_BASE_URL}",\n'
        '    authentication = @PactBrokerAuth(token = "${PACT_BROKER_TOKEN}"),\n'
        '    enablePendingPacts = "true",\n'
        '    providerBranch = "${GIT_BRANCH:}")\n'
        f"class {class_name} {{\n"
        "\n"
        "    /** The parameters each provider state was sent with in the pacts (one example each), as JSON. */\n"
        f"    static final Map<String, String> EXAMPLE_PARAMETERS = {examples};\n"
        "\n"
        "    @PactBrokerConsumerVersionSelectors\n"
        "    public static SelectorBuilder consumerVersionSelectors() {\n"
        "        return new SelectorBuilder().mainBranch().deployedOrReleased();\n"
        "    }\n"
        "\n"
        "    @BeforeEach\n"
        "    void target(PactVerificationContext context) {\n"
        '        String base = System.getenv().getOrDefault("PROVIDER_BASE_URL", "http://localhost:8080");\n'
        "        URI uri = URI.create(base);\n"
        '        int port = uri.getPort() == -1 ? ("https".equals(uri.getScheme()) ? 443 : 80) : uri.getPort();\n'
        "        context.setTarget(new HttpTestTarget(uri.getHost(), port, uri.getPath()));\n"
        '        boolean ci = "true".equals(System.getenv("CI"));\n'
        '        System.setProperty("pact.verifier.publishResults", String.valueOf(ci));\n'
        '        System.setProperty("pact.provider.version", System.getenv().getOrDefault("GIT_COMMIT", ""));\n'
        "    }\n"
        "\n"
        "    @TestTemplate\n"
        "    @ExtendWith(PactVerificationInvocationContextProvider.class)\n"
        "    void honoursThePacts(PactVerificationContext context) {\n"
        "        context.verifyInteraction();\n"
        "    }\n"
        "\n"
        f"{methods}"
        "}\n"
    )
    return content, class_name


def _go(provider: str, states: Sequence[ScaffoldState]) -> str:
    """A pact-go v2 provider verification test."""
    examples = "".join(
        f"\t{_go_string(state.name)}: {_go_string(_json_text(_example_params(state)))},\n" for state in states
    )
    handlers = ""
    for state in states:
        if not state.registered:
            handlers += f"\t\t\t// {_UNREGISTERED}\n"
        handlers += (
            f"\t\t\t{_go_string(state.name)}: func(setup bool, s models.ProviderState) "
            "(models.ProviderStateResponse, error) {\n"
            f"\t\t\t\t// {_TODO}\n"
            "\t\t\t\t_ = s.Parameters\n"
            "\t\t\t\treturn nil, nil\n"
            "\t\t\t},\n"
        )
    return (
        f"// Provider verification for {_file_stem(provider)} — generated by Apiome "
        "(apiome pact scaffold-provider-tests).\n"
        "// The broker and its token come from the environment; nothing secret is written here.\n"
        "package provider_test\n"
        "\n"
        "import (\n"
        '\t"os"\n'
        '\t"testing"\n'
        "\n"
        '\t"github.com/pact-foundation/pact-go/v2/models"\n'
        '\t"github.com/pact-foundation/pact-go/v2/provider"\n'
        ")\n"
        "\n"
        "// EXAMPLE_PARAMETERS holds the parameters each provider state was sent with in the pacts\n"
        "// (one example each), as JSON.\n"
        f"var EXAMPLE_PARAMETERS = map[string]string{{\n{examples}}}\n"
        "\n"
        "func envOr(name, fallback string) string {\n"
        '\tif value := os.Getenv(name); value != "" {\n'
        "\t\treturn value\n"
        "\t}\n"
        "\treturn fallback\n"
        "}\n"
        "\n"
        "func TestHonoursThePacts(t *testing.T) {\n"
        "\terr := provider.NewVerifier().VerifyProvider(t, provider.VerifyRequest{\n"
        f"\t\tProvider:                   {_go_string(provider)},\n"
        '\t\tProviderBaseURL:            envOr("PROVIDER_BASE_URL", "http://localhost:8080"),\n'
        '\t\tBrokerURL:                  os.Getenv("PACT_BROKER_BASE_URL"),\n'
        '\t\tBrokerToken:                os.Getenv("PACT_BROKER_TOKEN"),\n'
        "\t\tConsumerVersionSelectors: []provider.Selector{\n"
        "\t\t\t&provider.ConsumerVersionSelector{MainBranch: true},\n"
        "\t\t\t&provider.ConsumerVersionSelector{DeployedOrReleased: true},\n"
        "\t\t},\n"
        "\t\tEnablePending:              true,\n"
        '\t\tPublishVerificationResults: os.Getenv("CI") == "true",\n'
        '\t\tProviderVersion:            os.Getenv("GIT_COMMIT"),\n'
        '\t\tProviderBranch:             os.Getenv("GIT_BRANCH"),\n'
        f"\t\tStateHandlers: models.StateHandlers{{\n{handlers}\t\t}},\n"
        "\t})\n"
        "\tif err != nil {\n"
        "\t\tt.Fatal(err)\n"
        "\t}\n"
        "}\n"
    )


def _python(provider: str, states: Sequence[ScaffoldState]) -> str:
    """A pact-python 2 test: ``verify_with_broker`` plus a state-change dispatcher to mount in the app."""
    examples = "".join(f"    {_py_literal(state.name)}: {_py_literal(_example_params(state))},\n" for state in states)
    functions = ""
    table = ""
    for state, function in zip(states, _identifiers([state.name for state in states], "snake")):
        if not state.registered:
            functions += f"# {_UNREGISTERED}\n"
        functions += f"def {function}(params: dict) -> None:\n" f"    # {_TODO}\n" "    del params\n\n\n"
        table += f"    {_py_literal(state.name)}: {function},\n"
    return (
        f'"""Provider verification for {_file_stem(provider)} — generated by Apiome '
        "(apiome pact scaffold-provider-tests).\n"
        "\n"
        "The broker and its token come from the environment; nothing secret is written here.\n"
        "pact-python 2 sets provider states through a state-change URL: mount handle_state_change at\n"
        "PROVIDER_BASE_URL + /_pact/provider_states in the provider (test builds only).\n"
        '"""\n'
        "\n"
        "import os\n"
        "\n"
        "from pact import Verifier\n"
        "\n"
        f"PROVIDER = {_py_literal(provider)}\n"
        'PROVIDER_BASE_URL = os.environ.get("PROVIDER_BASE_URL", "http://localhost:8080")\n'
        "\n"
        "# The parameters each provider state was sent with in the pacts (one example each).\n"
        f"EXAMPLE_PARAMETERS = {{\n{examples}}}\n"
        "\n"
        "\n"
        f"{functions}"
        f"STATE_HANDLERS = {{\n{table}}}\n"
        "\n"
        "\n"
        "def handle_state_change(body: dict) -> None:\n"
        '    """Answer the verifier\'s POST {"state", "params", "action"}: set the state up on "setup"."""\n'
        '    if body.get("action", "setup") != "setup":\n'
        "        return\n"
        '    handler = STATE_HANDLERS.get(body.get("state"))\n'
        "    if handler is None:\n"
        "        raise LookupError(f\"no handler for the provider state {body.get('state')!r}\")\n"
        '    handler(body.get("params") or {})\n'
        "\n"
        "\n"
        "def test_honours_the_pacts() -> None:\n"
        "    verifier = Verifier(provider=PROVIDER, provider_base_url=PROVIDER_BASE_URL)\n"
        "    success, _logs = verifier.verify_with_broker(\n"
        '        broker_url=os.environ["PACT_BROKER_BASE_URL"],\n'
        '        broker_token=os.environ.get("PACT_BROKER_TOKEN"),\n'
        '        consumer_version_selectors=[{"mainBranch": True}, {"deployedOrReleased": True}],\n'
        "        enable_pending=True,\n"
        '        provider_states_setup_url=f"{PROVIDER_BASE_URL}/_pact/provider_states",\n'
        '        publish_version=os.environ.get("GIT_COMMIT"),\n'
        '        provider_version_branch=os.environ.get("GIT_BRANCH"),\n'
        '        publish_verification_results=os.environ.get("CI") == "true",\n'
        "    )\n"
        "    assert success == 0\n"
    )


# =============================================================================================
# The generator
# =============================================================================================


def scaffold_provider_test(
    provider: str, language: str, states: Sequence[ScaffoldState], *, pacts: int
) -> ProviderScaffold:
    """Write one provider verification test.

    Args:
        provider: The provider's name, as the pacts write it.
        language: One of :data:`LANGUAGES`.
        states: Every state the provider's selected pacts name (any order).
        pacts: How many pacts were selected, for the no-pacts notice.

    Returns:
        The file and its notices.

    Raises:
        ScaffoldError: ``provider-scaffold-language-unsupported`` for an unknown language.
    """
    if language not in LANGUAGES:
        raise ScaffoldError(
            CODE_LANGUAGE_UNSUPPORTED,
            f"'{language}' is not a scaffold language; choose one of {', '.join(LANGUAGES)}",
        )
    notices: List[ScaffoldNotice] = []
    if pacts == 0:
        notices.append(
            ScaffoldNotice(
                NOTICE_NO_PACTS,
                f"no consumer has a pact for {provider} on its main branch or deployed or released yet, "
                "so the file has no state handlers; generate it again once one is published",
            )
        )
    kept: List[ScaffoldState] = []
    for state in sorted(states, key=lambda item: item.name):
        if len(state.name) > MAX_STATE_NAME:
            notices.append(
                ScaffoldNotice(
                    NOTICE_STATE_LEFT_OUT,
                    f"a state name of {len(state.name)} characters is longer than {MAX_STATE_NAME}; "
                    "it was left out — add its handler by hand",
                    state.name[:80],
                )
            )
        elif len(kept) >= MAX_STATES:
            notices.append(
                ScaffoldNotice(
                    NOTICE_STATE_LEFT_OUT,
                    f"one file carries at most {MAX_STATES} state handlers; this one was left out",
                    state.name,
                )
            )
        else:
            kept.append(state)
    for state in kept:
        if not state.registered:
            notices.append(
                ScaffoldNotice(
                    NOTICE_STATE_UNREGISTERED,
                    "not registered in Apiome: hosted verification cannot set this state up until it is "
                    "(Contracts → a provider's Provider states)",
                    state.name,
                )
            )

    stem = _file_stem(provider)
    if language == "typescript":
        content, file_name = _typescript(provider, kept), f"{stem}.pact.test.ts"
    elif language == "java":
        content, class_name = _java(provider, kept)
        file_name = f"{class_name}.java"
    elif language == "go":
        content, file_name = _go(provider, kept), f"{stem.replace('-', '_')}_pact_test.go"
    else:
        content, file_name = _python(provider, kept), f"test_{stem.replace('-', '_')}_pact.py"
    return ProviderScaffold(language=language, file_name=file_name, content=content, states=kept, notices=notices)

"""The vocabularies a system can be told in. One owner for every word a theme changes.

A theme is words only: the names of the five layers, the commands and registers of
each layer, the final commands, the command and register of the one quantity that
must reach zero before the last step, and the codenames. Rules, costs, score, levels,
outcomes and error codes are the same in every theme.

Systems are always generated in the `legacy` vocabulary and then reworded
(`generate._reword`), so a seed describes the same structure in every theme.
"""

from dataclasses import dataclass

LEGACY = "legacy"
AIRCRAFT = "aircraft"
RESIDENCY = "residency"


@dataclass(frozen=True)
class Theme:
    name: str
    roles: tuple[str, ...]  # the five layers, lowest first
    # role -> (six preparation commands with the register each clears, two commands
    # that are never needed)
    commands: dict[str, tuple[tuple[tuple[str, str], ...], tuple[str, ...]]]
    final_step: tuple[str, str]  # last command of a unit, and its register
    last_final_step: tuple[str, str]  # the same for the unit of the last layer
    sync_command: str  # lowers the lag by one
    lag_register: str  # must be zero before the last layer's final command
    codenames: tuple[str, ...]  # carry no hint of a role


THEMES: dict[str, Theme] = {
    LEGACY: Theme(
        name=LEGACY,
        roles=("storage", "database", "middleware", "application", "gateway"),
        commands={
            "storage": (
                (
                    ("fsck", "filesystem"),
                    ("replay-journal", "journal"),
                    ("attach", "volume"),
                    ("scrub", "checksums"),
                    ("verify-raid", "array"),
                    ("resize", "quota"),
                ),
                ("format", "reinit"),
            ),
            "database": (
                (
                    ("recover", "wal"),
                    ("migrate", "schema"),
                    ("reindex", "indexes"),
                    ("unlock", "locks"),
                    ("vacuum", "bloat"),
                    ("promote", "replica-role"),
                ),
                ("reinit", "drop-wal"),
            ),
            "middleware": (
                (
                    ("rehydrate", "snapshot"),
                    ("rotate-keys", "keys"),
                    ("drain", "backlog"),
                    ("rebalance", "partitions"),
                    ("compact", "log-segments"),
                    ("reconnect", "peers"),
                ),
                ("purge", "reset-offsets"),
            ),
            "application": (
                (
                    ("warm-cache", "cache"),
                    ("load-config", "config"),
                    ("register", "registration"),
                    ("compile-assets", "assets"),
                    ("migrate-sessions", "sessions"),
                    ("seed-flags", "flags"),
                ),
                ("factory-reset", "rollback"),
            ),
            "gateway": (
                (
                    ("sync-routes", "routes"),
                    ("renew-cert", "certificate"),
                    ("health-gate", "healthchecks"),
                    ("pin-upstreams", "upstreams"),
                    ("reload-acl", "acl"),
                    ("warm-tls", "tls-sessions"),
                ),
                ("flush-routes", "force-failover"),
            ),
        },
        final_step=("start", "process"),
        last_final_step=("cutover", "traffic"),
        sync_command="sync",
        lag_register="replication_lag",
        codenames=(
            "alder", "basalt", "bramble", "cobalt", "flint", "garnet", "heron", "juniper",
            "kestrel", "larch", "linden", "marrow", "moss", "onyx", "osprey", "pumice",
            "quartz", "saffron", "sedge", "sorrel", "tallow", "tern", "thistle", "wren",
        ),  # fmt: skip
    ),
    # A captured aircraft of an unknown type, to be brought to take-off undamaged.
    AIRCRAFT: Theme(
        name=AIRCRAFT,
        roles=("power", "hydraulics", "avionics", "engines", "flight-control"),
        commands={
            "power": (
                (
                    ("connect-battery", "battery-bus"),
                    ("spin-apu", "apu"),
                    ("close-breakers", "breakers"),
                    ("sync-generators", "generators"),
                    ("warm-inverters", "inverters"),
                    ("test-ground", "grounding"),
                ),
                ("jettison-battery", "short-bus"),
            ),
            "hydraulics": (
                (
                    ("prime-pumps", "pumps"),
                    ("purge-air", "lines"),
                    ("pressurize", "accumulators"),
                    ("check-reservoir", "reservoir"),
                    ("cycle-valves", "valves"),
                    ("arm-backup", "backup-circuit"),
                ),
                ("dump-fluid", "overpressure"),
            ),
            "avionics": (
                (
                    ("align-inertial", "inertial-platform"),
                    ("load-database", "nav-database"),
                    ("boot-computers", "mission-computers"),
                    ("calibrate-air-data", "air-data"),
                    ("tune-radios", "radios"),
                    ("test-displays", "displays"),
                ),
                ("wipe-memory", "zeroize"),
            ),
            "engines": (
                (
                    ("open-fuel", "fuel-valves"),
                    ("motor-starter", "starter"),
                    ("light-igniters", "igniters"),
                    ("stabilize-idle", "idle"),
                    ("check-oil", "oil-pressure"),
                    ("bleed-compressor", "compressor"),
                ),
                ("hot-start", "dry-crank"),
            ),
            "flight-control": (
                (
                    ("free-controls", "control-locks"),
                    ("set-trim", "trim"),
                    ("test-surfaces", "surfaces"),
                    ("arm-stability", "stability-system"),
                    ("set-flaps", "flaps"),
                    ("release-brakes", "brakes"),
                ),
                ("blow-canopy", "cut-cables"),
            ),
        },
        final_step=("engage", "subsystem"),
        last_final_step=("takeoff", "flight"),
        sync_command="balance",
        lag_register="pressure_imbalance",
        codenames=(
            "arvo", "belto", "cendra", "dursk", "elvan", "fesk", "galdo", "hirt",
            "ivesk", "jarno", "keld", "lumo", "marn", "nesto", "orvik", "pesh",
            "quorn", "rask", "selto", "tarn", "ulvik", "vesh", "wendo", "zarn",
        ),  # fmt: skip
    ),
    # A residence permit from a state that publishes none of its rules.
    RESIDENCY: Theme(
        name=RESIDENCY,
        roles=("registry", "treasury", "insurance", "labour", "immigration"),
        commands={
            "registry": (
                (
                    ("certify-birth", "birth-record"),
                    ("legalize", "legalization"),
                    ("translate", "translation"),
                    ("register-address", "address"),
                    ("take-photo", "photograph"),
                    ("verify-identity", "identity"),
                ),
                ("renounce", "annul-record"),
            ),
            "treasury": (
                (
                    ("declare-income", "income-declaration"),
                    ("pay-stamp", "stamp-duty"),
                    ("open-account", "tax-account"),
                    ("clear-debts", "debt-clearance"),
                    ("prove-funds", "funds"),
                    ("assess", "assessment"),
                ),
                ("declare-insolvency", "close-account"),
            ),
            "insurance": (
                (
                    ("enroll", "enrollment"),
                    ("medical-exam", "examination"),
                    ("vaccinate", "vaccination-record"),
                    ("pay-premium", "premium"),
                    ("name-doctor", "physician"),
                    ("waive-history", "history-waiver"),
                ),
                ("opt-out", "cancel-cover"),
            ),
            "labour": (
                (
                    ("sign-contract", "contract"),
                    ("recognize-diploma", "diploma"),
                    ("sponsor", "sponsorship"),
                    ("register-employer", "employer"),
                    ("pass-interview", "interview"),
                    ("join-fund", "pension-fund"),
                ),
                ("resign", "dispute-contract"),
            ),
            "immigration": (
                (
                    ("give-fingerprints", "biometrics"),
                    ("book-slot", "appointment"),
                    ("pay-fee", "fee"),
                    ("background-check", "clearance"),
                    ("language-test", "language"),
                    ("sign-pledge", "pledge"),
                ),
                ("withdraw", "overstay"),
            ),
        },
        final_step=("submit", "dossier"),
        last_final_step=("collect", "permit"),
        sync_command="settle",
        lag_register="arrears",
        codenames=(
            "amber", "birch", "cedar", "dune", "ember", "fjord", "glen", "harbor",
            "iris", "jade", "koi", "lotus", "maple", "nova", "opal", "pearl",
            "quill", "reed", "sage", "tulip", "umber", "violet", "willow", "zenith",
        ),  # fmt: skip
    ),
}

# Every role of every theme and the layer it is. Role names are unique across themes.
ROLE_LAYER: dict[str, int] = {
    role: layer
    for theme in THEMES.values()
    for layer, role in enumerate(theme.roles, start=1)
}


def theme_of(name: str) -> Theme:
    if name not in THEMES:
        raise ValueError(f"unknown theme {name!r}; one of: {', '.join(THEMES)}")
    return THEMES[name]

"""Reading `git` launches in the acceptance tests: where the replace-ref options sit, and watching launches.

Not a test file. A launch is `git [global options] <subcommand> ...`; the global options are `--no-replace-objects`,
`-C <path>` and `-c <key=value>`, in whatever order the launcher wrote them (acceptance's own helper writes the option
before `-C`, the index-safety helper after it), so no position is assumed."""

from types import SimpleNamespace

CONFIG_PAIR = "core.useReplaceRefs=false"


def split_launch(args):
    """(options, subcommand argv) of a `git` launch."""
    assert args[0] == "git", args
    no_replace, config, path, i = False, [], None, 1
    while i < len(args):
        if args[i] == "--no-replace-objects":
            no_replace, i = True, i + 1
        elif args[i] == "-C":
            path, i = args[i + 1], i + 2
        elif args[i] == "-c":
            config.append(args[i + 1])
            i += 2
        else:
            break
    return SimpleNamespace(no_replace=no_replace, config=config, path=path), list(args[i:])


def ignores_replace_refs(args, env=None):
    """The launch ignores replace refs: by the global option wherever it sits, or by the environment variable."""
    options, _ = split_launch(args)
    return options.no_replace or (env or {}).get("GIT_NO_REPLACE_OBJECTS") == "1"


def protected_project_read(args):
    """The launch carries both the option and the configuration pair (which, unlike the option, reaches the Git that a
    submodule's status starts)."""
    options, _ = split_launch(args)
    return options.no_replace and CONFIG_PAIR in options.config

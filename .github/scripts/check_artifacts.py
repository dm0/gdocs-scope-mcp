"""Verify artifacts and installed MCP entry points without Google access."""

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

TOOLSET_SPECIFIC_TOOLS = {
    'v1': {'docs_append', 'docs_insert_before', 'docs_insert_after',
           'docs_resolve_comment', 'docs_reopen_comment'},
    'v2': {'docs_insert', 'docs_comment_status'},
}


def run(*command, env=None):
    """Run a bounded CLI command and retain diagnostics on failure."""
    result = subprocess.run(command, env=env, text=True, capture_output=True,
                            timeout=180, check=False)
    if result.returncode:
        raise RuntimeError(
            f'{command!r} failed ({result.returncode})\n'
            f'{result.stdout}\n{result.stderr}',
        )
    return result.stdout


def executable(environment, name):
    """Resolve console scripts in an explicitly isolated environment."""
    return str(environment / ('Scripts' if os.name == 'nt' else 'bin')
               / (name + '.exe' if os.name == 'nt' else name))


def check_contents(wheel, sdist):
    """Require byte-identical source modules in both distributions."""
    modules = {str(path.relative_to('src')): path.read_bytes()
               for path in Path('src/gdocs_scope_mcp').rglob('*.py')}
    with zipfile.ZipFile(wheel) as archive:
        metadata = next(name for name in archive.namelist()
                        if name.endswith('.dist-info/METADATA'))
        package_version = BytesParser().parsebytes(archive.read(metadata))[
            'Version']
        for name, content in modules.items():
            assert archive.read(name) == content, ('wheel', name)
    with tarfile.open(sdist) as archive:
        root = sdist.name.removesuffix('.tar.gz')
        metadata = archive.extractfile(root + '/PKG-INFO')
        assert metadata is not None
        assert BytesParser().parsebytes(metadata.read())['Version'] == (
            package_version)
        for name, content in modules.items():
            member = archive.extractfile(root + '/src/' + name)
            assert member is not None, ('sdist missing', name)
            assert member.read() == content, ('sdist', name)
    print(f'Both artifacts include {len(modules)} identical source modules.')
    return package_version


def run_mcp(client, server, action, *arguments, env):
    """Pass application settings explicitly to the CLI's child server."""
    with tempfile.TemporaryDirectory(prefix='gdocs-mcp-config-') as temporary:
        config = Path(temporary) / 'mcp.json'
        config.write_text(json.dumps({'mcpServers': {'artifact': {
            'command': server,
            'env': {key: value for key, value in env.items()
                    if key.startswith('GDOCS_SCOPE_MCP_')},
        }}}))
        return run(client, action, str(config), *arguments, env=env)


def discover_catalogs(client, server, env):
    """Discover both explicit toolsets and reject missing or mixed tools."""
    catalogs = {}
    for version, required in TOOLSET_SPECIFIC_TOOLS.items():
        selected_env = {**env, 'GDOCS_SCOPE_MCP_TOOLSET_VERSION': version}
        tools = json.loads(run_mcp(client, server, 'list', '--json',
                                   env=selected_env))['tools']
        names = {tool['name'] for tool in tools}
        missing = ({'server_info', 'docs_read'} | required) - names
        unexpected = {name for other, tools in TOOLSET_SPECIFIC_TOOLS.items()
                      if other != version for name in tools} & names
        assert not missing and not unexpected, (
            f'{version}: missing={sorted(missing)}, '
            f'unexpected={sorted(unexpected)}'
        )
        catalogs[version] = tools
    return catalogs


def check_installation(artifact, directory, constraints, catalogs, env, *,
                       package_version):
    """Install one artifact and discover tools through its own STDIO server."""
    environment = directory / artifact.suffix.removeprefix('.')
    run('uv', 'venv', '--python', sys.executable, str(environment))
    python = executable(environment, 'python')
    run('uv', 'pip', 'install', '--python', python, '--constraint',
        str(constraints), str(artifact.resolve()))
    run(executable(environment, 'gdocs-scope-mcp-auth'), '--help', env=env)
    client = executable(environment, 'fastmcp')
    server = executable(environment, 'gdocs-scope-mcp')
    identity = json.loads(run_mcp(client, server, 'call', '--target',
                                  'server_info', '--json', env=env))
    assert not identity['is_error'], identity
    info = identity['structured_content']
    assert Path(info['package_path']).resolve().is_relative_to(
        environment.resolve()), info['package_path']
    assert info['package_version'] == package_version
    discovered = discover_catalogs(client, server, env)
    for version, tools in catalogs.items():
        assert discovered[version] == tools, (
            f'{artifact.name}: installed {version} catalog '
            'differs from source.'
        )
        print(f'{artifact.name}: {version} catalog ({len(tools)} tools) OK.')
    print(f'{artifact.name}: isolated CLI/auth and identity OK.')


def main():
    """Check exactly one wheel and sdist built from the current checkout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    wheels = list(args.directory.glob('*.whl'))
    sdists = list(args.directory.glob('*.tar.gz'))
    assert len(wheels) == len(sdists) == 1, (wheels, sdists)
    package_version = check_contents(wheels[0], sdists[0])
    with tempfile.TemporaryDirectory(prefix='gdocs-artifacts-') as temporary:
        directory = Path(temporary)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('GOOGLE_DOCS_', 'GOOGLE_DRIVE_',
                                      'GDOCS_SCOPE_MCP_', 'GOG_'))}
        env['GDOCS_SCOPE_MCP_TOKEN'] = str(directory / 'missing-token.json')
        config = directory / 'config.json'
        config.write_text('{}\n')
        env['GDOCS_SCOPE_MCP_CONFIG'] = str(config)
        source_scripts = Path(sys.executable).parent
        catalogs = discover_catalogs(str(source_scripts / 'fastmcp'),
                                     str(source_scripts / 'gdocs-scope-mcp'),
                                     env)
        constraints = directory / 'constraints.txt'
        run('uv', 'export', '--frozen', '--no-dev', '--no-emit-project',
            '--no-hashes', '--output-file', str(constraints))
        for artifact in (wheels[0], sdists[0]):
            check_installation(artifact, directory, constraints, catalogs, env,
                               package_version=package_version)


if __name__ == '__main__':
    main()

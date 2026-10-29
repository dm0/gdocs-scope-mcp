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


def check_installation(artifact, directory, constraints, tools, env, *,
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
    identity = json.loads(run(client, 'call', '--command', server, '--target',
                              'server_info', '--json', env=env))
    assert not identity['is_error'], identity
    info = identity['structured_content']
    assert Path(info['package_path']).resolve().is_relative_to(
        environment.resolve()), info['package_path']
    assert info['package_version'] == package_version
    discovered = json.loads(run(client, 'list', '--command', server,
                                '--json', env=env))['tools']
    assert discovered == tools, 'Installed catalog differs from source.'
    print(f'{artifact.name}: isolated CLI/auth and {len(tools)} MCP tools OK.')


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
        source_scripts = Path(sys.executable).parent
        tools = json.loads(run(str(source_scripts / 'fastmcp'), 'list',
            '--command', str(source_scripts / 'gdocs-scope-mcp'),
            '--json', env=env))['tools']
        assert {'server_info', 'docs_read', 'docs_append'} <= {
            tool['name'] for tool in tools}
        constraints = directory / 'constraints.txt'
        run('uv', 'export', '--frozen', '--no-dev', '--no-emit-project',
            '--no-hashes', '--output-file', str(constraints))
        for artifact in (wheels[0], sdists[0]):
            check_installation(artifact, directory, constraints, tools, env,
                               package_version=package_version)


if __name__ == '__main__':
    main()

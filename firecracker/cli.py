from typing_extensions import Annotated

import typer
from rich import print
from rich.console import Console
from rich.table import Table
from firecracker import MicroVM

app = typer.Typer()
console = Console()


@app.command()
def create(
    name: Annotated[str, typer.Option()] = None,
    kernel_file: Annotated[str, typer.Option()] = None,
    base_rootfs: Annotated[str, typer.Option()] = None,
    rootfs_url: Annotated[str, typer.Option()] = None,
    vcpu: Annotated[int, typer.Option()] = 2,
    mem_size_mib: Annotated[int, typer.Option()] = 1024,
    ip_addr: Annotated[str, typer.Option()] = None,
    bridge: Annotated[bool, typer.Option()] = False,
    bridge_name: Annotated[str, typer.Option()] = None,
    mmds_enabled: Annotated[bool, typer.Option()] = False,
    mmds_ip: Annotated[str, typer.Option()] = None,
    # labels: Annotated[dict, typer.Option()],
    working_dir: Annotated[str, typer.Option()] = None,
    expose_ports: Annotated[bool, typer.Option()] = False,
    host_port: Annotated[int, typer.Option()] = None,
    dest_port: Annotated[int, typer.Option()] = None,
    verbose: Annotated[bool, typer.Option()] = False,
):
    MicroVM(
        name=name,
        kernel_file=kernel_file,
        base_rootfs=base_rootfs,
        rootfs_url=rootfs_url,
        vcpu=vcpu,
        mem_size_mib=mem_size_mib,
        ip_addr=ip_addr,
        bridge=bridge,
        bridge_name=bridge_name,
        mmds_enabled=mmds_enabled,
        mmds_ip=mmds_ip,
        # labels=labels,
        working_dir=working_dir,
        expose_ports=expose_ports,
        host_port=host_port,
        dest_port=dest_port,
        verbose=verbose,
    ).create()


@app.command()
def rm(id: Annotated[str, typer.Argument()]):
    MicroVM().delete(id=id)


@app.command()
def resume(id: Annotated[str, typer.Argument()]):
    MicroVM().resume(id=id)


@app.command()
def pause(id: Annotated[str, typer.Argument()]):
    MicroVM().pause(id=id)


@app.command()
def inspect(id: Annotated[str, typer.Argument()]):
    print(MicroVM().inspect(id=id))


@app.command()
def ps():
    table = Table("MicroVM ID", "STATUS", "IP", "PID", "NAMES")
    for vm in MicroVM.list():
        table.add_row(vm["id"], vm["state"], vm["ip_addr"], str(vm["pid"]), vm["name"])

    console.print(table)


@app.command()
def version():
    print("Firecracker version")


def main() -> None:
    app()

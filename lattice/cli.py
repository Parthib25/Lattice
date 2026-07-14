import os
import asyncio
import typer
import uvicorn
from lattice.database.connection import DatabaseConnectionManager
from lattice.database.models import Base, Repository
from lattice.database.repository import UserRepository, RuleRepository

app = typer.Typer(help="Lattice Command Line Interface utilities")
db_app = typer.Typer(help="Database operations")
app.add_typer(db_app, name="db")
user_app = typer.Typer(help="User account management")
app.add_typer(user_app, name="user")
repo_app = typer.Typer(help="Repository management")
app.add_typer(repo_app, name="repo")

# Read DB url from env
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./lattice.db")

async def async_db_init():
    manager = DatabaseConnectionManager(DATABASE_URL, ssl_verify=False)
    async with manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await manager.close()
    typer.echo("Database tables initialized successfully.")

async def async_create_admin(username: str, email: str):
    manager = DatabaseConnectionManager(DATABASE_URL, ssl_verify=False)
    async with manager.get_session() as session:
        user = await UserRepository.create(
            session, username=username, email=email, role="ADMIN"
        )
        await session.commit()
        typer.echo(f"Admin user '{user.username}' created successfully (ID: {user.id}).")
    await manager.close()

async def async_add_repo(name: str, vcs_url: str, custom_domain: str = None):
    manager = DatabaseConnectionManager(DATABASE_URL, ssl_verify=False)
    async with manager.get_session() as session:
        repo = await RuleRepository.create_repository(
            session, name=name, vcs_url=vcs_url, custom_domain=custom_domain
        )
        await session.commit()
        typer.echo(f"Repository '{repo.name}' added successfully (ID: {repo.id}).")
    await manager.close()


@db_app.command("init")
def db_init():
    """Drops and recreates all database tables."""
    asyncio.run(async_db_init())


@user_app.command("create-admin")
def create_admin(
    username: str = typer.Option(..., "--username", "-u", help="Admin username"),
    email: str = typer.Option(..., "--email", "-e", help="Unique email address for SSO mapping")
):
    """Creates a new administrator account in the database."""
    asyncio.run(async_create_admin(username, email))


@repo_app.command("add")
def add_repo(
    name: str = typer.Option(..., "--name", "-n", help="Friendly repository name"),
    vcs_url: str = typer.Option(..., "--url", "-u", help="VCS URL or local directory path"),
    custom_domain: str = typer.Option(None, "--custom-domain", "-d", help="Optional Sourcegraph search API domain")
):
    """Adds a new target repository for evaluation checks."""
    asyncio.run(async_add_repo(name, vcs_url, custom_domain))


@app.command("start")
def start_server(
    host: str = typer.Option("127.0.0.1", "--host", help="Server host binding IP"),
    port: int = typer.Option(8000, "--port", "-p", help="Server port binding")
):
    """Starts the FastAPI Web REST API server."""
    typer.echo(f"Starting Lattice REST Server on http://{host}:{port}...")
    uvicorn.run("lattice.server:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    app()

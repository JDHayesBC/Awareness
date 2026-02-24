#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Dependency checker for Pattern Persistence System (PPS).

This script verifies that all required dependencies are installed and 
configured correctly for PPS MCP tools to work.
"""

import asyncio
import os
import sys
import subprocess
import importlib
from pathlib import Path
from typing import Dict, List, Tuple


class DependencyChecker:
    """Comprehensive dependency checker for PPS installation."""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.success: List[str] = []
    
    def check_python_version(self) -> bool:
        """Check Python version compatibility."""
        version = sys.version_info
        required = (3, 11)
        
        if version >= required:
            self.success.append(f"✅ Python {version.major}.{version.minor}.{version.micro} (>= 3.11 required)")
            return True
        else:
            self.errors.append(f"❌ Python {version.major}.{version.minor}.{version.micro} < 3.11 (required)")
            return False
    
    def check_python_packages(self) -> bool:
        """Check required Python packages are installed."""
        required_packages = [
            'mcp',
            'aiohttp', 
            'aiosqlite',
            'chromadb',
            'redis',
            'discord',
            'fastapi',
            'jinja2',
            'uvicorn',
            'python-dotenv'
        ]
        
        all_good = True
        for package in required_packages:
            try:
                # Handle packages with different import names
                import_name = {
                    'discord': 'discord.py',
                    'python-dotenv': 'dotenv'
                }.get(package, package)
                
                if import_name == 'discord.py':
                    importlib.import_module('discord')
                elif import_name == 'dotenv':
                    importlib.import_module('dotenv')
                else:
                    importlib.import_module(import_name)
                    
                self.success.append(f"✅ {package}")
            except ImportError:
                self.errors.append(f"❌ {package} not installed (pip install {package})")
                all_good = False
        
        return all_good
    
    def check_docker_services(self) -> bool:
        """Check Docker and required services."""
        # Check Docker is installed
        try:
            result = subprocess.run(['docker', '--version'], 
                                  capture_output=True, text=True, check=True)
            self.success.append(f"✅ Docker installed: {result.stdout.strip()}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.errors.append("❌ Docker not installed or not in PATH")
            return False
        
        # Check Docker Compose
        try:
            result = subprocess.run(['docker-compose', '--version'], 
                                  capture_output=True, text=True, check=True)
            self.success.append(f"✅ Docker Compose: {result.stdout.strip()}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.warnings.append("⚠️ Docker Compose not found (may use 'docker compose' instead)")
        
        # Check if services are running (non-blocking)
        self._check_service_health()
        return True
    
    def _check_service_health(self) -> None:
        """Check if PPS Docker services are running."""
        services = {
            'ChromaDB': 'http://localhost:8000/api/v1/heartbeat',
            'Graphiti': 'http://localhost:8001/health',
            'PPS Web': 'http://localhost:8202/'
        }
        
        try:
            import requests
            for service, url in services.items():
                try:
                    response = requests.get(url, timeout=2)
                    if response.status_code == 200:
                        self.success.append(f"✅ {service} service running")
                    else:
                        self.warnings.append(f"⚠️ {service} service responded with {response.status_code}")
                except requests.RequestException:
                    self.warnings.append(f"⚠️ {service} service not accessible (may be stopped)")
        except ImportError:
            self.warnings.append("⚠️ requests package not available for service health checks")
    
    def check_file_structure(self) -> bool:
        """Check required directories and files exist."""
        claude_home = Path.home() / ".claude"
        awareness_path = Path(__file__).parent.parent
        
        required_paths = [
            claude_home / "data",
            awareness_path / "pps",
            awareness_path / "daemon", 
            awareness_path / "docker",
        ]
        
        required_files = [
            awareness_path / "pps" / "server.py",
            awareness_path / "daemon" / "startup_context.py",
            awareness_path / "docker" / "docker-compose.yml",
            awareness_path / "requirements.txt"
        ]
        
        all_good = True
        
        # Check directories
        for path in required_paths:
            if path.exists():
                self.success.append(f"✅ Directory: {path}")
            else:
                self.errors.append(f"❌ Missing directory: {path}")
                all_good = False
        
        # Check files
        for file_path in required_files:
            if file_path.exists():
                self.success.append(f"✅ File: {file_path.name}")
            else:
                self.errors.append(f"❌ Missing file: {file_path}")
                all_good = False
        
        return all_good
    
    def check_environment_variables(self) -> bool:
        """Check important environment variables."""
        important_vars = [
            'CLAUDE_HOME',
            'HOME'
        ]
        
        optional_vars = [
            'CHROMADB_URL',
            'GRAPHITI_URL', 
            'PPS_DB_PATH',
            'CONVERSATION_DB_PATH'
        ]
        
        # Check required
        for var in important_vars:
            value = os.getenv(var)
            if value:
                self.success.append(f"✅ {var}={value}")
            else:
                if var == 'CLAUDE_HOME':
                    # Auto-detect CLAUDE_HOME
                    claude_home = Path.home() / ".claude"
                    if claude_home.exists():
                        self.success.append(f"✅ {var} auto-detected: {claude_home}")
                    else:
                        self.warnings.append(f"⚠️ {var} not set, ~/.claude doesn't exist")
                else:
                    self.warnings.append(f"⚠️ {var} not set")
        
        # Check optional
        for var in optional_vars:
            value = os.getenv(var)
            if value:
                self.success.append(f"✅ {var}={value}")
            else:
                self.warnings.append(f"⚠️ {var} not set (using defaults)")
        
        return True
    
    async def check_mcp_integration(self) -> bool:
        """Check MCP server can start and respond."""
        try:
            awareness_path = Path(__file__).parent.parent
            server_path = awareness_path / "pps" / "server.py"
            
            if not server_path.exists():
                self.errors.append(f"❌ PPS MCP server not found: {server_path}")
                return False
            
            # Try to import the server module to check for import errors
            sys.path.insert(0, str(awareness_path / "pps"))
            try:
                import server
                self.success.append("✅ PPS MCP server imports successfully")
            except ImportError as e:
                self.errors.append(f"❌ PPS MCP server import error: {e}")
                return False
            finally:
                sys.path.remove(str(awareness_path / "pps"))
            
            return True
        except Exception as e:
            self.errors.append(f"❌ MCP check failed: {e}")
            return False
    
    def check_claude_code_cli(self) -> bool:
        """Check Claude Code CLI is available."""
        try:
            result = subprocess.run(['claude', '--version'], 
                                  capture_output=True, text=True, check=True)
            self.success.append(f"✅ Claude Code CLI: {result.stdout.strip()}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.errors.append("❌ Claude Code CLI not found (install from anthropic.com/claude-code)")
            return False
    
    def print_results(self) -> None:
        """Print comprehensive results."""
        print("=" * 60)
        print("PPS DEPENDENCY CHECK RESULTS")
        print("=" * 60)
        
        if self.success:
            print(f"\n✅ SUCCESS ({len(self.success)} items):")
            for item in self.success:
                print(f"   {item}")
        
        if self.warnings:
            print(f"\n⚠️ WARNINGS ({len(self.warnings)} items):")
            for item in self.warnings:
                print(f"   {item}")
        
        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)} items):")
            for item in self.errors:
                print(f"   {item}")
        
        print("\n" + "=" * 60)
        
        if self.errors:
            print("❌ INSTALLATION HAS ISSUES - See errors above")
            print("   Refer to docs/INSTALLATION.md for resolution steps")
        elif self.warnings:
            print("⚠️ INSTALLATION MOSTLY READY - Some optional components missing")
            print("   PPS should work but may have reduced functionality")
        else:
            print("✅ INSTALLATION COMPLETE - All dependencies satisfied")
            print("   PPS should work without issues")
        
        print("=" * 60)
    
    def get_exit_code(self) -> int:
        """Get appropriate exit code based on results."""
        if self.errors:
            return 1
        elif self.warnings:
            return 2  
        else:
            return 0


async def main():
    """Main dependency check routine."""
    print("Checking Pattern Persistence System (PPS) dependencies...\n")
    
    checker = DependencyChecker()
    
    # Run all checks
    checks = [
        ("Python Version", checker.check_python_version),
        ("Python Packages", checker.check_python_packages),
        ("Docker Services", checker.check_docker_services),
        ("File Structure", checker.check_file_structure),
        ("Environment Variables", checker.check_environment_variables),
        ("Claude Code CLI", checker.check_claude_code_cli),
        ("MCP Integration", checker.check_mcp_integration),
    ]
    
    for check_name, check_func in checks:
        print(f"Checking {check_name}...")
        if asyncio.iscoroutinefunction(check_func):
            await check_func()
        else:
            check_func()
    
    checker.print_results()
    return checker.get_exit_code()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
"""Construye la aplicación (base de datos, migraciones y servicios) en un solo lugar."""
from __future__ import annotations

import logging
import threading

from .config import Config
from .core.secrets_store import SecretStore
from .core.settings import Settings
from .db import Database
from .services.auth import AuthService
from .services.backup import BackupService
from .services.catalog import CatalogService
from .services.documents import DocumentService
from .services.finance import FinanceService
from .services.inventory import InventoryService
from .services.open_items import AP, AR, OpenItems
from .services.prefs import PrefsService
from .services.printing import PrintingService
from .services.reports import ReportService
from .services.sales import SalesService
from .services.sync import SyncService
from .services.users import UserService

log = logging.getLogger("pospy")


class AppContext:
    def __init__(self, config: Config):
        config.ensure_dirs()
        self.config = config
        self.db = Database(config.db_path)
        self.db.migrate()
        self.settings = Settings(self.db)
        self.secrets = SecretStore(self.db, config.data_dir, config.master_key)
        self.auth = AuthService(self.db, self.settings, config.data_dir, config.setup_code)
        self.users = UserService(self.db)
        self.prefs = PrefsService(self.db)
        self.catalog = CatalogService(self.db)
        self.inventory = InventoryService(self.db, self.settings)
        self.sales = SalesService(self.db, self.settings, self.inventory)
        self.printing = PrintingService(self.db, self.settings, self.sales)
        self.documents = DocumentService(self.db, self.settings, config, self.printing)
        self.receivables = OpenItems(self.db, self.settings, AR)
        self.payables = OpenItems(self.db, self.settings, AP)
        self.finance = FinanceService(self.db, self.settings)
        self.reports = ReportService(self.db, self.settings)
        self.backups = BackupService(self.db, self.settings, config.backups_dir)
        self.sync = SyncService(self.db, self.settings, self.secrets, self.inventory, config.imports_dir)
        self.auth.prepare_setup()
        self._stop = threading.Event()
        self._scheduler: threading.Thread | None = None

    def start_scheduler(self, interval_s: float = 60.0) -> None:
        """Tareas periódicas: sincronizaciones programadas y copia automática diaria."""
        def loop() -> None:
            while not self._stop.wait(interval_s):
                self.run_periodic()
        self.run_periodic()
        self._scheduler = threading.Thread(target=loop, name="pospy-scheduler", daemon=True)
        self._scheduler.start()

    def run_periodic(self) -> None:
        for task in (self.backups.auto_backup_if_due, self.sync.tick):
            try:
                task()
            except Exception:  # noqa: BLE001 - una tarea fallida no detiene el servidor
                log.exception("Tarea periódica fallida: %s", task.__name__)

    def stop(self) -> None:
        self._stop.set()

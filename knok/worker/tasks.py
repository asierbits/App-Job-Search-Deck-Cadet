"""Registro de tareas: importar los módulos que definen tareas con @task."""
import knok.services.crawling  # noqa: F401  crawl_companies
import knok.services.mailer  # noqa: F401  send_email, deliver_simulated_replies
import knok.services.search  # noqa: F401  run_search, refresh_ats_boards
import knok.services.tracking  # noqa: F401  mark_followups_due

"""Dropbox folder watcher for courthouse photo import.

Polls a Dropbox folder for new photos using cursor-based change detection.
Resolves county and notice_type from folder path convention:
  /{root}/{county}/{notice_type}/photo.jpg

Persists cursor and processed-file state to disk to survive restarts.
"""

import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import dropbox
from dropbox.exceptions import ApiError
from dropbox.files import FileMetadata, DeletedMetadata, FolderMetadata

import config

logger = logging.getLogger(__name__)

# Valid notice types that can appear in folder paths
VALID_NOTICE_TYPES = {
    "foreclosure", "tax_sale", "tax_delinquent", "probate",
    "eviction", "code_violation", "divorce",
}
# Counties are not restricted — any county folder name in Dropbox is accepted.
# Previously hardcoded to Knox/Blount; now supports any market.
KNOWN_COUNTIES = {"knox", "blount"}  # Known counties (used for info logging only)
VALID_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def _get_client() -> dropbox.Dropbox:
    """Create authenticated Dropbox client using refresh token."""
    if not config.DROPBOX_REFRESH_TOKEN:
        raise ValueError("DROPBOX_REFRESH_TOKEN not set in .env")
    if not config.DROPBOX_APP_KEY:
        raise ValueError("DROPBOX_APP_KEY not set in .env")

    return dropbox.Dropbox(
        oauth2_refresh_token=config.DROPBOX_REFRESH_TOKEN,
        app_key=config.DROPBOX_APP_KEY,
        app_secret=config.DROPBOX_APP_SECRET or None,
    )


def _load_state(path: Path) -> dict:
    """Load JSON state from disk (delegates to config.load_state)."""
    return config.load_state(path)


def _save_state(path: Path, data: dict) -> None:
    """Save JSON state to disk atomically (delegates to config.save_state)."""
    config.save_state(path, data)


def _parse_folder_path(file_path: str, root_folder: str = "") -> tuple[str, str] | None:
    """Extract county and notice_type from Dropbox file path.

    Expected: /{root}/{county}/{notice_type}/filename.ext
    Returns (county, notice_type) or None if path doesn't match convention.
    """
    # Normalize path separators
    parts = file_path.strip("/").split("/")

    # Strip root folder prefix if set
    if root_folder:
        root_parts = root_folder.strip("/").split("/")
        if parts[:len(root_parts)] == root_parts:
            parts = parts[len(root_parts):]

    # Need at least: county / notice_type / filename
    if len(parts) < 3:
        return None

    county_raw = parts[0].lower()
    type_raw = parts[1].lower().replace("-", "_").replace(" ", "_")

    if county_raw not in KNOWN_COUNTIES:
        logger.info("New county detected in Dropbox path: %s (not in default Knox/Blount)", parts[0])

    if type_raw not in VALID_NOTICE_TYPES:
        logger.debug("Unrecognized notice type in path: %s", parts[1])
        return None

    return parts[0].title(), type_raw


def check_storage_usage(dbx: dropbox.Dropbox) -> None:
    """Log Dropbox storage usage and warn if above threshold."""
    try:
        usage = dbx.users_get_space_usage()
        used = usage.used
        if usage.allocation.is_individual():
            total = usage.allocation.get_individual().allocated
        else:
            total = usage.used  # team accounts — can't determine allocation easily
            return

        percent = (used / total * 100) if total > 0 else 0
        logger.info("Dropbox storage: %.1f MB / %.1f MB (%.0f%%)",
                     used / 1e6, total / 1e6, percent)

        if percent >= config.DROPBOX_STORAGE_WARN_PERCENT:
            logger.warning(
                "⚠ Dropbox storage at %.0f%% — consider cleaning processed photos",
                percent,
            )
    except Exception as e:
        logger.warning("Could not check Dropbox storage: %s", e)


def _delete_from_dropbox(dbx: dropbox.Dropbox, file_path: str) -> bool:
    """Delete a file from Dropbox after processing."""
    try:
        dbx.files_delete_v2(file_path)
        logger.debug("Deleted from Dropbox: %s", file_path)
        return True
    except ApiError as e:
        logger.warning("Failed to delete %s from Dropbox: %s", file_path, e)
        return False


def poll_once(
    dbx: dropbox.Dropbox,
    root_folder: str = "",
    delete_after: bool = True,
) -> list[dict]:
    """Run one poll cycle: check for new files, download, parse metadata.

    Returns list of dicts: {local_path, county, notice_type, dropbox_path, filename}
    """
    state = _load_state(config.DROPBOX_STATE_FILE)
    photo_state = _load_state(config.PHOTO_STATE_FILE)
    processed_files = set(photo_state.get("processed", []))

    cursor = state.get("cursor")
    folder_path = f"/{root_folder.strip('/')}" if root_folder else ""

    # Get new files since last cursor
    new_entries = []
    try:
        if cursor:
            try:
                result = dbx.files_list_folder_continue(cursor)
            except ApiError as e:
                if e.error.is_reset():
                    logger.warning("Dropbox cursor expired, re-scanning folder")
                    cursor = None
                else:
                    raise

        if not cursor:
            result = dbx.files_list_folder(
                folder_path or "", recursive=True, limit=100
            )

        new_entries.extend(result.entries)
        while result.has_more:
            result = dbx.files_list_folder_continue(result.cursor)
            new_entries.extend(result.entries)

        # Always persist cursor
        state["cursor"] = result.cursor
        state["last_poll"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _save_state(config.DROPBOX_STATE_FILE, state)

    except ApiError as e:
        logger.error("Dropbox API error during poll: %s", e)
        return []

    # Filter to new image files
    downloads = []
    for entry in new_entries:
        if not isinstance(entry, FileMetadata):
            continue

        ext = Path(entry.name).suffix.lower()
        if ext not in VALID_EXTENSIONS:
            continue

        if entry.path_lower in processed_files:
            logger.debug("Already processed: %s", entry.path_display)
            continue

        # Parse county/type from folder path
        parsed = _parse_folder_path(entry.path_display, root_folder)
        if not parsed:
            logger.warning("Could not determine county/type from path: %s", entry.path_display)
            continue

        county, notice_type = parsed
        downloads.append({
            "dropbox_path": entry.path_display,
            "dropbox_path_lower": entry.path_lower,
            "county": county,
            "notice_type": notice_type,
            "filename": entry.name,
        })

    if not downloads:
        logger.info("Dropbox poll: no new photos found")
        return []

    logger.info("Dropbox poll: %d new photos to process", len(downloads))

    # Download to temp directory
    tmp_dir = Path(tempfile.mkdtemp(prefix="tnpn_photos_"))
    results = []

    for item in downloads:
        try:
            local_path = tmp_dir / item["filename"]
            dbx.files_download_to_file(str(local_path), item["dropbox_path"])
            item["local_path"] = local_path
            results.append(item)
            logger.debug("Downloaded: %s → %s", item["dropbox_path"], local_path)
        except ApiError as e:
            logger.warning("Failed to download %s: %s", item["dropbox_path"], e)

    return results


def mark_processed(
    dbx: dropbox.Dropbox | None,
    items: list[dict],
    delete_after: bool = True,
) -> None:
    """Mark files as processed and optionally delete from Dropbox."""
    photo_state = _load_state(config.PHOTO_STATE_FILE)
    processed = set(photo_state.get("processed", []))

    for item in items:
        processed.add(item["dropbox_path_lower"])

        if delete_after and dbx:
            _delete_from_dropbox(dbx, item["dropbox_path"])

    photo_state["processed"] = sorted(processed)
    photo_state["last_processed"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_state(config.PHOTO_STATE_FILE, photo_state)


def _run_skip_trace_guarded(notices: list) -> None:
    """Fit-gate → Tracerfy → death/identity guard, in the canonical order.

    Mirrors ``main.actor_main``: only wholesale-fit leads are submitted to paid
    skip trace (Phase 4 fit gate, fails CLOSED), and the death/identity guard
    runs STRICTLY between the trace and the DataSift upload so dead/wrong-person
    phones never reach the dialer (W5-CR-02 / G5-CR-02). No-op when Tracerfy is
    not configured. Never raises — a trace/guard failure must not abort the run.
    """
    if not config.TRACERFY_API_KEY:
        return
    try:
        from tracerfy_skip_tracer import batch_skip_trace
        from skip_trace_guard import (
            is_tracerfy_eligible,
            guard_all,
            apply_contact_fallbacks,
            handle_credits_exhausted,
        )
    except ImportError as e:
        logger.warning("Skip-trace modules unavailable (%s) — skipping trace", e)
        return

    # Phase 4 fit gate — fail CLOSED on blank/0 score (single source of truth).
    eligible = [n for n in notices if is_tracerfy_eligible(n, config.SKIP_TRACE_MIN_FIT)]
    logger.info("Tracerfy fit-gate: %d/%d eligible (min_fit=%s)",
                len(eligible), len(notices), config.SKIP_TRACE_MIN_FIT)
    if not eligible:
        return
    try:
        stats = batch_skip_trace(eligible)
        if (stats or {}).get("credits_exhausted"):
            handle_credits_exhausted(eligible, stats)
        # Death/identity guard — STRICTLY between trace and upload.
        g = guard_all(eligible)
        apply_contact_fallbacks(eligible)
        logger.info(
            "Tracerfy: %s/%s matched, %s phones | guard: %s phone(s) suppressed, "
            "%s DM(s) unconfirmed",
            (stats or {}).get("matched", 0),
            (stats or {}).get("submitted", len(eligible)),
            (stats or {}).get("phones_found", 0),
            g.get("suppressed_phones", 0), g.get("unconfirmed", 0),
        )
    except Exception as e:
        logger.warning("Tracerfy/guard failed: %s — continuing", e)


def _upload_and_notify(notices: list) -> None:
    """Upload the batch to DataSift (enrich + skip trace) and send the Slack summary.

    Guard suppression has already run on ``notices`` (see ``_process_group``), so
    the DataSift CSV carries only contact data that cleared the death/identity guard.
    """
    upload_result = None
    if config.DATASIFT_EMAIL and config.DATASIFT_PASSWORD:
        try:
            import asyncio as _asyncio
            from datasift_formatter import write_datasift_split_csvs
            from datasift_uploader import upload_datasift_split, upload_to_datasift

            csv_infos = write_datasift_split_csvs(notices)
            if len(csv_infos) > 1:
                upload_result = _asyncio.run(
                    upload_datasift_split(csv_infos, enrich=True, skip_trace=True)
                )
            else:
                upload_result = _asyncio.run(
                    upload_to_datasift(csv_infos[0]["path"], enrich=True, skip_trace=True)
                )
            if upload_result.get("success"):
                logger.info("DataSift upload: %s", upload_result.get("message", "OK"))
            else:
                logger.error("DataSift upload failed: %s", upload_result.get("message"))
        except Exception as e:
            logger.error("DataSift upload error: %s", e)
            upload_result = {"success": False, "message": str(e)}

    if config.SLACK_WEBHOOK_URL:
        try:
            from slack_notifier import send_slack_notification
            send_slack_notification(notices, upload_result=upload_result)
        except Exception as e:
            logger.warning("Slack notification failed: %s", e)


def _process_group(county: str, notice_type: str, group_dir: Path) -> bool:
    """Process one (county, notice_type) batch of photos end to end.

    OCR → enrich → fit-gated + guarded skip trace → CSV → DataSift → Slack.

    Returns True only if at least one record was produced and the CSV was
    written. The caller uses this to decide whether the source photos may be
    deleted from Dropbox — a False return means NOTHING was produced, so the
    source must be retained, never deleted (W5-CR-01 data loss).
    """
    from photo_importer import process_photos
    from enrichment_pipeline import PipelineOptions, run_enrichment_pipeline
    from data_formatter import write_csv
    from datetime import datetime

    api_key = config.ANTHROPIC_API_KEY or None
    notices = process_photos(
        folder=group_dir, county=county, notice_type=notice_type, api_key=api_key,
    )
    if not notices:
        return False

    opts = PipelineOptions(source_label=f"Dropbox watcher ({county}/{notice_type})")
    notices = run_enrichment_pipeline(notices, opts)
    if not notices:
        return False

    # Phase 4 fit gate + Phase 5 death/identity guard MUST run BEFORE any CSV
    # write / upload so suppressed dead/wrong-person phones never reach the
    # dialer (W5-CR-02 / G5-CR-02). Mirrors main.actor_main ordering.
    _run_skip_trace_guarded(notices)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"{county.lower()}_{notice_type}_{timestamp}.csv"
    write_csv(notices, filename=filename)
    logger.info("Output: %s (%d records)", filename, len(notices))

    _upload_and_notify(notices)
    return True


def run_watcher(
    poll_interval: int | None = None,
    delete_after: bool = True,
    max_polls: int | None = None,
) -> None:
    """Run the Dropbox watcher loop.

    Args:
        poll_interval: Seconds between polls (default from config).
        delete_after: Delete photos from Dropbox after processing.
        max_polls: Maximum number of poll cycles (None = infinite).
    """
    interval = poll_interval or config.DROPBOX_POLL_INTERVAL
    root_folder = config.DROPBOX_ROOT_FOLDER

    logger.info("Starting Dropbox watcher (interval=%ds, root=%s, delete=%s)",
                interval, root_folder or "(root)", delete_after)

    dbx = _get_client()
    check_storage_usage(dbx)

    poll_count = 0
    while max_polls is None or poll_count < max_polls:
        poll_count += 1
        logger.info("--- Poll %d ---", poll_count)

        items = poll_once(dbx, root_folder=root_folder, delete_after=delete_after)

        if items:
            # Group by county + notice_type
            groups: dict[tuple[str, str], list[dict]] = {}
            for item in items:
                key = (item["county"], item["notice_type"])
                groups.setdefault(key, []).append(item)

            for (county, notice_type), group_items in groups.items():
                logger.info("Processing %d photos: %s / %s", len(group_items), county, notice_type)

                # Create temp folder with just this group's photos
                group_dir = Path(tempfile.mkdtemp(prefix=f"tnpn_{county}_{notice_type}_"))
                for item in group_items:
                    if "local_path" in item and item["local_path"].exists():
                        shutil.copy2(item["local_path"], group_dir / item["filename"])

                # Process the group in isolation: one bad group must not kill the
                # long-running daemon (W5-WR-01), and a group that produced NO
                # records must NOT delete its source photos (W5-CR-01 data loss).
                produced_records = False
                try:
                    produced_records = _process_group(county, notice_type, group_dir)
                except Exception:
                    logger.exception(
                        "Group %s/%s failed — source photos retained for retry",
                        county, notice_type,
                    )
                    produced_records = False
                finally:
                    # Delete the source photo ONLY when we actually produced and
                    # persisted output. On failure keep it in Dropbox so an
                    # un-reshootable courthouse capture is never silently lost.
                    mark_processed(
                        dbx, group_items,
                        delete_after=(delete_after and produced_records),
                    )
                    if not produced_records:
                        logger.warning(
                            "No records produced for %s/%s — %d source photo(s) "
                            "NOT deleted (kept for re-OCR)",
                            county, notice_type, len(group_items),
                        )
                    shutil.rmtree(group_dir, ignore_errors=True)

            # Clean up download temp dir
            for item in items:
                if "local_path" in item:
                    parent = item["local_path"].parent
                    if parent.exists():
                        shutil.rmtree(parent, ignore_errors=True)
                    break

        # Check storage after processing
        if items:
            check_storage_usage(dbx)

        if max_polls is not None and poll_count >= max_polls:
            break

        logger.info("Sleeping %d seconds until next poll...", interval)
        time.sleep(interval)

    logger.info("Dropbox watcher stopped after %d polls", poll_count)

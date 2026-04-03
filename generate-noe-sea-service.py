#!/usr/bin/env python3
import dataclasses
import logging
import shutil
import subprocess
from datetime import date
from pathlib import PosixPath
from typing import Tuple

import pymupdf
import gspread
import requests
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)
VOYAGE_TYPES = {"Near Coastal": "NC"}
VESSEL_TYPES = {"Sailing Yacht": "Sail"}


@dataclasses.dataclass(frozen=True)
class TemplateRowColumnOffsets:
    vessel_name: float
    flag: float
    gt: float
    length: float
    type: float
    voyage: float
    capacity: float
    from_date: float
    to_date: float
    duration_months: float
    duration_days: float
    actual_sea_service: float
    standby_service: float
    yard_service: float
    watch_keeping: float


@dataclasses.dataclass(frozen=True)
class TemplateTotalColumnOffsets:
    duration_months: float
    duration_days: float
    actual_sea_service: float
    standby_service: float
    yard_service: float
    watch_keeping: float


@dataclasses.dataclass(frozen=True)
class TemplatePage:
    number: int
    row_offsets: list[float]
    column_offsets: TemplateRowColumnOffsets
    total_row_offset: float
    total_column_offset: TemplateTotalColumnOffsets


@dataclasses.dataclass(frozen=True)
class VesselAndVoyageDetails:
    _source: str
    vessel_name: str
    vessel_registration: str
    flag: str
    gt: float
    length: float
    type: str
    voyage: str
    capacity: str
    from_date: date
    to_date: date
    duration_months: int
    duration_days: int
    actual_sea_service: int
    standby_service: int
    yard_service: int
    watch_keeping: int


def get_google_drive_credentials() -> Credentials:
    result = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True,
        text=True,
        check=True,
    )
    access_token = result.stdout.strip()
    return Credentials(
        token=access_token,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
        ],
    )


def get_voyage_details() -> list[VesselAndVoyageDetails]:
    client = gspread.authorize(get_google_drive_credentials())
    spreadsheet = client.open_by_url(
        "https://docs.google.com/spreadsheets/d/1ubA1PKxatPHmf8Dl4AaMI4eohYDuzjo7Amy7DTi9XZk/edit"
    )

    entries = []
    for worksheet in spreadsheet.worksheets():
        if not worksheet.title.startswith("Log "):
            logger.warning(f"Ignoring sheet: {worksheet.title}")
            continue

        for x, row in enumerate(worksheet.get("A3:O99999")):
            from_date = date.strptime(row[7], "%d/%m/%Y")
            to_date = date.strptime(row[8], "%d/%m/%Y")
            duration_days = int(row[9]) if row[9] else 0
            actual_sea_service = int(row[10]) if row[10] else 0

            entry = VesselAndVoyageDetails(
                _source=f"Sheet: {worksheet.title}, Row: {3 + x}",
                vessel_name=row[0],
                vessel_registration=row[2],
                flag=row[1],
                gt=row[4],
                length=float(row[3]),
                type=VESSEL_TYPES.get(row[5], row[5]),
                voyage=VOYAGE_TYPES.get(row[13], row[13]),
                capacity=row[6],
                from_date=from_date,
                to_date=to_date,
                duration_months=int((to_date - from_date).days / 31),
                duration_days=duration_days,
                actual_sea_service=actual_sea_service,
                standby_service=0,
                yard_service=max(duration_days - actual_sea_service, 0),
                watch_keeping=actual_sea_service,
            )

            if entry.from_date > date.today():
                logger.warning(f"Ignoring future entry: {entry.vessel_name} ({entry.from_date})")
                continue

            if not all(
                [
                    entry.vessel_name,
                    entry.flag,
                    entry.gt,
                    entry.length,
                    entry.type,
                    entry.capacity,
                    entry.duration_days,
                    any(
                        [
                            entry.actual_sea_service,
                            entry.standby_service,
                            entry.yard_service,
                        ]
                    ),
                ]
            ):
                logger.warning(f"Ignoring entry: {entry}")
                continue

            entries.append(entry)
    return entries


def check_overlapping_dates(voyage_details: list[VesselAndVoyageDetails]) -> None:
    sorted_entries = sorted(voyage_details, key=lambda e: e.from_date)
    for i, a in enumerate(sorted_entries):
        for b in sorted_entries[i + 1 :]:
            if b.from_date >= a.to_date:
                break
            logger.error(
                f"Overlapping dates: {a.vessel_name} ({a.from_date}–{a.to_date})"
                f" overlaps {b.vessel_name} ({b.from_date}–{b.to_date})"
                f" [{a._source} / {b._source}]"
            )


def insert_cell(page, x: float, y: float, text) -> None:
    if text in {None, ""}:
        return
    page.insert_text((x + 3, y), str(text), fontsize=7, color=(0, 0, 0))


def write_page(
    template_file: PosixPath,
    template_page: TemplatePage,
    voyage_details: list[VesselAndVoyageDetails],
    output_path: PosixPath,
) -> None:
    if len(voyage_details) > len(template_page.row_offsets):
        raise ValueError(
            f"Was given {len(voyage_details)} but can only handle {len(template_page.row_offsets)} rows"
        )

    with pymupdf.open(template_file) as doc:
        for i, entry in enumerate(voyage_details):
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.vessel_name,
                template_page.row_offsets[i],
                entry.vessel_name,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.vessel_name,
                template_page.row_offsets[i] + 10,
                entry.vessel_registration,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.flag,
                template_page.row_offsets[i],
                entry.flag,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.gt,
                template_page.row_offsets[i],
                entry.gt,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.length,
                template_page.row_offsets[i],
                f"{entry.length}m",
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.length,
                template_page.row_offsets[i] + 10,
                "LOA",
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.type,
                template_page.row_offsets[i],
                entry.type,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.voyage,
                template_page.row_offsets[i],
                entry.voyage,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.capacity,
                template_page.row_offsets[i],
                entry.capacity,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.from_date,
                template_page.row_offsets[i],
                entry.from_date.strftime("%d/%m/%Y"),
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.to_date,
                template_page.row_offsets[i],
                entry.to_date.strftime("%d/%m/%Y"),
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.duration_months,
                template_page.row_offsets[i],
                entry.duration_months,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.duration_days,
                template_page.row_offsets[i],
                entry.duration_days,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.actual_sea_service,
                template_page.row_offsets[i],
                entry.actual_sea_service,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.standby_service,
                template_page.row_offsets[i],
                entry.standby_service,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.yard_service,
                template_page.row_offsets[i],
                entry.yard_service,
            )
            insert_cell(
                doc[template_page.number],
                template_page.column_offsets.watch_keeping,
                template_page.row_offsets[i],
                entry.watch_keeping,
            )

        insert_cell(
            doc[template_page.number],
            template_page.total_column_offset.duration_months,
            template_page.total_row_offset,
            sum(e.duration_months for e in voyage_details),
        )
        insert_cell(
            doc[template_page.number],
            template_page.total_column_offset.duration_days,
            template_page.total_row_offset,
            sum(e.duration_days for e in voyage_details),
        )
        insert_cell(
            doc[template_page.number],
            template_page.total_column_offset.actual_sea_service,
            template_page.total_row_offset,
            sum(e.actual_sea_service for e in voyage_details),
        )
        insert_cell(
            doc[template_page.number],
            template_page.total_column_offset.standby_service,
            template_page.total_row_offset,
            sum(e.standby_service for e in voyage_details),
        )
        insert_cell(
            doc[template_page.number],
            template_page.total_column_offset.yard_service,
            template_page.total_row_offset,
            sum(e.yard_service for e in voyage_details),
        )
        insert_cell(
            doc[template_page.number],
            template_page.total_column_offset.watch_keeping,
            template_page.total_row_offset,
            sum(e.watch_keeping for e in voyage_details),
        )

        logger.info(f"Writing {len(voyage_details)} entries to {output_path}")
        doc.select([template_page.number])
        doc.save(output_path)


def download_template(
    template_dir: PosixPath, current_file: str, download_url: str
) -> PosixPath:
    if not template_dir.is_dir():
        logger.debug(f"Creating template directory: {template_dir}")
        template_dir.mkdir(parents=True)

    template_file = template_dir / current_file
    if template_file.is_file():
        logger.debug(f"Already have template, skipping download: {template_file}")
        return template_file

    logger.debug(f"Downloading template to {template_file}")
    r = requests.get(download_url)
    r.raise_for_status()
    with template_file.open("wb") as f:
        f.write(r.content)

    return template_file


def get_template(template_dir: PosixPath) -> Tuple[PosixPath, TemplatePage, TemplatePage]:
    template_file = download_template(
        template_dir,
        "Deck_Yacht_MSF_4343_Rev_1223.pdf",
        "https://assets.publishing.service.gov.uk/media/65858be6fc07f3000d8d4710/Deck_Yacht_MSF_4343_Rev_1223.pdf",
    )

    return (
        template_file,
        TemplatePage(
            number=1,  # Page 2 = section 3, sea service
            row_offsets=[311.5, 338.4, 365.2, 391.9, 418.8, 445.6],
            column_offsets=TemplateRowColumnOffsets(
                vessel_name=23.5,
                flag=115.7,
                gt=178.2,
                length=220.8,
                type=263.2,
                voyage=298.6,
                capacity=341.2,
                from_date=419.2,
                to_date=468.8,
                duration_months=518.4,
                duration_days=568.0,
                actual_sea_service=610.5,
                standby_service=660.1,
                yard_service=709.8,
                watch_keeping=765.5,
            ),
            total_row_offset=485.0,
            total_column_offset=TemplateTotalColumnOffsets(
                duration_months=518.4,
                duration_days=568.0,
                actual_sea_service=610.5,
                standby_service=660.1,
                yard_service=709.8,
                watch_keeping=765.5,
            ),
        ),
        TemplatePage(
            number=2,  # Page 3 = continuation of section 3, additional sea service
            row_offsets=[
                83.2,
                109.3,
                135.6,
                161.9,
                188.2,
                214.6,
                240.8,
                267.1,
                293.4,
                319.7,
                346.0,
                372.2,
            ],
            column_offsets=TemplateRowColumnOffsets(
                vessel_name=22.0,
                flag=121.4,
                gt=186.8,
                length=229.4,
                type=271.9,
                voyage=307.4,
                capacity=349.9,
                from_date=427.9,
                to_date=477.4,
                duration_months=527.0,
                duration_days=576.7,
                actual_sea_service=619.1,
                standby_service=668.8,
                yard_service=718.4,
                watch_keeping=774.1,
            ),
            total_row_offset=411.8,
            total_column_offset=TemplateTotalColumnOffsets(
                duration_months=527.0,
                duration_days=576.7,
                actual_sea_service=619.1,
                standby_service=668.8,
                yard_service=718.4,
                watch_keeping=774.1,
            ),
        ),
    )


def clean_outputs(output_dir: PosixPath) -> PosixPath:
    if output_dir.is_dir():
        shutil.rmtree(output_dir)
    output_dir.mkdir()
    logger.debug(f"Using clean output path: {output_dir}")
    return output_dir


def main():
    logging.basicConfig(level=logging.INFO)

    voyage_details = get_voyage_details()
    check_overlapping_dates(voyage_details)

    template_file, first_page, additional_page = get_template(PosixPath("template/"))
    output_dir = clean_outputs(PosixPath("output/"))

    # Write in date order
    voyage_details = sorted(voyage_details, key=lambda entry: entry.from_date)

    write_page(
        template_file,
        first_page,
        voyage_details[0 : len(first_page.row_offsets)],
        output_dir / "page-1.pdf",
    )
    if len(voyage_details) > len(first_page.row_offsets):
        remaining_voyages = voyage_details[len(first_page.row_offsets) :]

        additional_pages = [
            remaining_voyages[i : i + len(additional_page.row_offsets)]
            for i in range(
                0, len(remaining_voyages), len(additional_page.row_offsets)
            )
        ]
        for i, page in enumerate(additional_pages):
            write_page(
                template_file,
                additional_page,
                page,
                output_dir / f"page-{i + 2}.pdf",
            )

    with pymupdf.open() as merged_pdf:
        for file in sorted(output_dir.glob("page-*.pdf")):
            merged_pdf.insert_pdf(pymupdf.open(file))
        merged_pdf.save(output_dir / "sea-service.pdf")

        logger.info(
            f"Merged {merged_pdf.page_count} pages into {output_dir / 'sea-service.pdf'}"
        )


if __name__ == "__main__":
    main()

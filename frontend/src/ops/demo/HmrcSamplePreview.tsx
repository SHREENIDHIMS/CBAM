import { useState } from 'react'
import itemCsv from '../../../../backend/tests/fixtures/cds/hmrc_official_examples/import_item.csv?raw'
import headerCsv from '../../../../backend/tests/fixtures/cds/hmrc_official_examples/import_header.csv?raw'
import taxCsv from '../../../../backend/tests/fixtures/cds/hmrc_official_examples/import_tax_lines.csv?raw'

type Report = 'items' | 'header' | 'tax'
type CsvRow = Record<string, string>

const reports: Record<Report, { label: string; filename: string; csv: string; columns: string[] }> =
  {
    items: {
      label: 'Import items',
      filename: 'import_item.csv',
      csv: itemCsv,
      columns: [
        'Entry Identifier',
        'Item Number',
        'Commodity Code',
        'Goods Description',
        'Country of Origin',
        'Net Mass',
        'Customs Value',
        'Invoice Currency',
        'Acceptance Date',
      ],
    },
    header: {
      label: 'Declaration header',
      filename: 'import_header.csv',
      csv: headerCsv,
      columns: [
        'Entry Identifier',
        'Importer EORI',
        'Declarant EORI',
        'Item Count',
        'Customs Value',
        'Invoice Currency',
        'Acceptance Date',
      ],
    },
    tax: {
      label: 'Tax lines',
      filename: 'import_tax_lines.csv',
      csv: taxCsv,
      columns: [
        'Entry Identifier',
        'Item Number',
        'Commodity Code',
        'Country of Origin',
        'Customs Value',
        'Tax Type 1',
        'Tax Amount 1',
      ],
    },
  }

function parseCsv(csv: string): { headers: string[]; rows: CsvRow[] } {
  const records: string[][] = []
  let record: string[] = []
  let field = ''
  let quoted = false
  for (let index = 0; index < csv.length; index += 1) {
    const char = csv[index]
    if (char === '"') {
      if (quoted && csv[index + 1] === '"') {
        field += '"'
        index += 1
      } else {
        quoted = !quoted
      }
    } else if (char === ',' && !quoted) {
      record.push(field)
      field = ''
    } else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && csv[index + 1] === '\n') index += 1
      record.push(field)
      if (record.some((value) => value !== '')) records.push(record)
      record = []
      field = ''
    } else {
      field += char
    }
  }
  if (field || record.length) {
    record.push(field)
    records.push(record)
  }
  const [headers = [], ...data] = records
  return {
    headers,
    rows: data.map((values) =>
      Object.fromEntries(headers.map((key, index) => [key, values[index] ?? ''])),
    ),
  }
}

const parsed = Object.fromEntries(
  (Object.keys(reports) as Report[]).map((key) => [key, parseCsv(reports[key].csv)]),
) as Record<Report, ReturnType<typeof parseCsv>>

function download(report: Report) {
  const { csv, filename } = reports[report]
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function HmrcSamplePreview() {
  const [selected, setSelected] = useState<Report>('items')
  const [allColumns, setAllColumns] = useState(false)
  const report = reports[selected]
  const data = parsed[selected]
  const columns = allColumns ? data.headers : report.columns
  const mrn = parsed.header.rows[0]?.['Entry Identifier'] ?? '—'

  return (
    <main className="min-h-screen bg-[#f6f7f4] text-slate-900">
      <header className="border-b border-slate-200 bg-white px-5 py-4 sm:px-8">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-emerald-700">
              CBAM / Development preview
            </p>
            <h1 className="text-2xl font-semibold tracking-tight">HMRC customs data sample</h1>
          </div>
          <span className="rounded-full bg-amber-100 px-3 py-1 text-sm font-medium text-amber-900">
            Synthetic data
          </span>
        </div>
      </header>

      <div className="mx-auto max-w-7xl space-y-6 px-5 py-8 sm:px-8">
        <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm leading-relaxed text-amber-950">
          <h2 className="mb-1 font-semibold">Example only</h2>
          <p>
            These CSVs use the exact column headers from HMRC’s published blank examples. Every data
            value is invented. This is a local preview of the input files, not an imported batch or
            a compliance decision.
          </p>
          <p className="mt-2">
            A masked real report is still needed to confirm date and monetary formats before
            production use.{' '}
            <a
              className="font-medium underline"
              href="https://www.gov.uk/guidance/get-customs-data-for-import-and-export-declarations"
              target="_blank"
              rel="noreferrer"
            >
              HMRC report guidance
            </a>
          </p>
        </section>

        <section aria-label="Sample overview" className="grid gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-600">Declaration</p>
            <p className="mt-2 break-all font-mono text-lg font-semibold">{mrn}</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-600">Import item rows</p>
            <p className="mt-2 text-3xl font-semibold">{parsed.items.rows.length}</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-600">Matched report files</p>
            <p className="mt-2 text-3xl font-semibold">3</p>
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-5">
            <div>
              <h2 className="text-xl font-semibold">Source reports</h2>
              <p className="mt-1 text-sm text-slate-600">
                Header, item and tax lines join on the same entry identifier.
              </p>
            </div>
            <button
              type="button"
              onClick={() => download(selected)}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
            >
              Download {report.filename}
            </button>
          </div>
          <div
            role="tablist"
            aria-label="HMRC sample reports"
            className="flex flex-wrap gap-2 border-b border-slate-200 px-5 py-3"
          >
            {(Object.keys(reports) as Report[]).map((key) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={selected === key}
                onClick={() => {
                  setSelected(key)
                  setAllColumns(false)
                }}
                className={
                  selected === key
                    ? 'rounded-md bg-emerald-700 px-3 py-2 text-sm font-medium text-white'
                    : 'rounded-md px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100'
                }
              >
                {reports[key].label} <span className="opacity-75">({parsed[key].rows.length})</span>
              </button>
            ))}
          </div>
          <div className="flex items-center justify-between gap-3 px-5 py-3 text-sm text-slate-600">
            <span>
              {data.headers.length} official columns · {data.rows.length} synthetic row
              {data.rows.length === 1 ? '' : 's'}
            </span>
            <label className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={allColumns}
                onChange={(event) => setAllColumns(event.target.checked)}
              />
              Show all columns
            </label>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-max text-left text-sm">
              <caption className="sr-only">{report.label} sample data</caption>
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  {columns.map((column) => (
                    <th
                      scope="col"
                      key={column}
                      className="whitespace-nowrap px-5 py-3 font-medium"
                    >
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, index) => (
                  <tr key={index} className="border-t border-slate-100">
                    {columns.map((column) => (
                      <td key={column} className="max-w-72 whitespace-nowrap px-5 py-3">
                        {row[column] || '—'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <p className="text-sm text-slate-600">
          Preview is available only from the local development server. The live app requires
          Supabase, the API and a signed-in account.
        </p>
      </div>
    </main>
  )
}

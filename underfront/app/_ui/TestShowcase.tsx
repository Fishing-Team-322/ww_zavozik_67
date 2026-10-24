"use client";

import { useState, type ReactNode } from "react";
import { AlertTriangle, ArrowRight, Check, CircleHelp, Plus, Trash2 } from "lucide-react";
import CompanyIdenticonAvatar from "@/src/shared/ui/AbstractAvatar/AbstractAvatar";
import {
  AreaChart, Badge, BarChart, Button, Card, ChartCard, ChartEmptyState,
  ChartLegend, ChartTooltip, Checkbox, ConfirmDialog, DateField, DateRangeField,
  Dialog, DonutChart, EmptyState, ErrorState, Icon, Input, KpiCard,
  KpiCardGroup, Label, LayeredCard, LineChart, MinimalSortableTable,
  Pagination, Radio, RadioGroup, SearchInput, Select, Skeleton, Spinner,
  SplitCard, Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
  Tabs, Textarea, type Column,
} from "@/src/shared/ui";
import { FormModal, InfoHint, PageHeader, PageLayout, SectionCard, Stepper } from "@/src/widgets/cabinet-shell";
import { CashflowForecastChart, DEFAULT_SCENARIO, RiskCard, ScenarioControls, type ScenarioParams } from "@/src/widgets/finance-panels";
import { BarSparkline, MetricTile, SignalCard, Sparkline, TrendChip } from "@/src/widgets/dashboard-metrics";
import { cashflowDays, chartData, chartSeries, donutData, mockRisk, mockSignals, operations, type OperationRow } from "./mock-data";

const formatAmount = (value: number) => value.toLocaleString("ru-RU") + " ₽";
const tableColumns: Column<OperationRow>[] = [
  { key: "date", label: "Дата", sortable: true },
  { key: "counterparty", label: "Контрагент", sortable: true },
  { key: "amount", label: "Сумма", sortable: true, render: (value) => formatAmount(Number(value)) },
  { key: "status", label: "Статус", render: (value) => <Badge variant={value === "Проведено" ? "success" : "warning"}>{String(value)}</Badge> },
];
const selectOptions = [
  { value: "retail", label: "Розничные продажи" },
  { value: "services", label: "Услуги" },
  { value: "other", label: "Другое", disabled: true },
];
const buttonCases = [
  { variant: "default", label: "Основная" },
  { variant: "secondary", label: "Вторичная" },
  { variant: "outline", label: "Контурная" },
  { variant: "danger", label: "Опасная" },
  { variant: "ghost", label: "Текстовая" },
  { variant: "back", label: "Назад" },
] as const;
const badgeCases = ["default", "brand", "success", "warning", "danger"] as const;
const badgeTones = ["subtle", "soft", "outline", "solid"] as const;

function ShowcaseSection({ id, title, description, children }: { id: string; title: string; description?: string; children: ReactNode }) {
  return (
    <SectionCard id={id} className="scroll-mt-24 p-5 sm:p-6">
      <div className="mb-5">
        <h2 className="text-xl font-semibold">{title}</h2>
        {description ? <p className="mt-1 text-sm text-[color:var(--text-secondary)]">{description}</p> : null}
      </div>
      {children}
    </SectionCard>
  );
}

function DemoLabel({ children }: { children: ReactNode }) {
  return <p className="mb-2 text-xs font-medium uppercase tracking-wide text-[color:var(--text-secondary)]">{children}</p>;
}

export function TestShowcase() {
  const [notice, setNotice] = useState("");
  const [name, setName] = useState("ООО «Пример»");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("retail");
  const [checked, setChecked] = useState(true);
  const [radioValue, setRadioValue] = useState("month");
  const [date, setDate] = useState("23.10.2026");
  const [fromDate, setFromDate] = useState("20.10.2026");
  const [toDate, setToDate] = useState("27.10.2026");
  const [tablePage, setTablePage] = useState(1);
  const [page, setPage] = useState(2);
  const [scenario, setScenario] = useState<ScenarioParams>(DEFAULT_SCENARIO);
  const [modal, setModal] = useState<"dialog" | "confirm" | "form" | null>(null);

  return (
    <PageLayout>
        <div className="space-y-6">
          <nav aria-label="Разделы каталога" className="flex flex-wrap gap-x-5 gap-y-2 text-sm font-medium text-[color:var(--accent)]">
            {[
              ["buttons", "Кнопки"], ["forms", "Поля и формы"], ["selection", "Выбор"],
              ["states", "Состояния"], ["cards", "Карточки"], ["tables", "Таблицы"],
              ["charts", "Графики"], ["finance", "Финансы"], ["layout", "Составные блоки"],
              ["dialogs", "Диалоги"],
            ].map(([id, label]) => <a key={id} href={"#" + id}>{label}</a>)}
          </nav>
          <p aria-live="polite" className="min-h-5 text-sm text-[color:var(--text-secondary)]">{notice}</p>

          <ShowcaseSection id="buttons" title="Кнопки и метки" description="Варианты, размеры, загрузка и отключённое состояние.">
            <DemoLabel>Варианты Button</DemoLabel>
            <div className="flex flex-wrap items-center gap-3">
              {buttonCases.map(({ variant, label }) => <Button key={variant} variant={variant} onClick={() => setNotice("Нажата кнопка: " + label)}>{label}</Button>)}
            </div>
            <div className="mt-5 grid gap-5 lg:grid-cols-2">
              <div><DemoLabel>Размеры и иконка</DemoLabel><div className="flex flex-wrap items-center gap-3"><Button size="sm">Малая</Button><Button size="md">Средняя</Button><Button size="lg">Большая</Button><Button size="icon" aria-label="Добавить"><Plus size={18} /></Button></div></div>
              <div><DemoLabel>Состояния</DemoLabel><div className="flex flex-wrap items-center gap-3"><Button loading>Загрузка</Button><Button disabled>Недоступна</Button><Button variant="danger" disabled>Удалить</Button></div></div>
            </div>
            <div className="mt-5"><DemoLabel>Badge: все варианты и тона</DemoLabel><div className="flex flex-wrap gap-x-6 gap-y-3">{badgeCases.flatMap((variant) => badgeTones.map((tone) => <Badge key={variant + tone} variant={variant} tone={tone}>{variant} · {tone}</Badge>))}</div></div>
            <div className="mt-5 flex flex-wrap items-center gap-5"><DemoLabel>Icon</DemoLabel><Icon icon={Check} tone="success" /><Icon icon={AlertTriangle} tone="danger" size="lg" /><Icon icon={CircleHelp} tone="muted" size="sm" /></div>
          </ShowcaseSection>

          <ShowcaseSection id="forms" title="Поля и формы" description="Пустое, заполненное, с подсказкой, ошибкой, загрузкой и disabled.">
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              <Input label="Пустое поле" placeholder="Введите название" />
              <Input label="Заполненное поле" value={name} onChange={(event) => setName(event.target.value)} helperText="Можно изменить значение" />
              <Input label="Ошибка в поле" defaultValue="ошибка@" error="Введите корректный email" type="email" />
              <Input label="Отключённое поле" value="Недоступно" readOnly disabled />
              <Input label="Пароль" defaultValue="example-secret" secretToggle />
              <Input label="Малое поле" inputSize="sm" defaultValue="Размер sm" />
              <Input label="Большое поле" inputSize="lg" defaultValue="Размер lg" />
              <SearchInput label="Поиск" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Найти компонент" />
              <SearchInput label="Поиск загружается" loading placeholder="Поиск" />
              <SearchInput label="Поиск отключён" disabled placeholder="Поиск" />
              <Select label="Категория" options={selectOptions} value={category} onChange={(event) => setCategory(event.target.value)} helperText="Откройте список с клавиатуры или мышью" />
              <Select label="С поиском" searchable options={selectOptions} placeholder="Выберите категорию" />
              <Select label="Ошибка выбора" options={selectOptions} error="Выберите доступное значение" />
              <Select label="Выбор отключён" options={selectOptions} disabled />
              <Select label="Пустой список" options={[]} searchable emptyTitle="Вариантов нет" />
              <div><Label htmlFor="manual-input">Отдельный Label</Label><Input id="manual-input" placeholder="Подпись связана с полем" /></div>
              <Textarea label="Комментарий" defaultValue="Пример заполненного многострочного поля" helperText="Тестовый текст" />
              <Textarea label="Ошибка комментария" error="Нужно добавить описание" />
              <Textarea label="Комментарий недоступен" value="Только просмотр" readOnly disabled />
            </div>
          </ShowcaseSection>

          <ShowcaseSection id="selection" title="Выбор и даты" description="Checkbox, Radio, календарь и диапазон дат.">
            <div className="grid gap-6 lg:grid-cols-2">
              <div><DemoLabel>Checkbox</DemoLabel><div className="flex flex-wrap gap-5"><Checkbox label="Пустой" /><Checkbox label="Выбранный" checked={checked} onChange={(event) => setChecked(event.target.checked)} /><Checkbox label="Частичный" indeterminate /><Checkbox label="Отключённый" disabled checked /></div></div>
              <div><DemoLabel>Radio и RadioGroup</DemoLabel><div className="space-y-3"><div className="flex gap-4"><Radio label="Первый" name="single-radio" defaultChecked /><Radio label="Второй" name="single-radio" /><Radio label="Недоступен" name="single-radio" disabled /></div><RadioGroup name="period" value={radioValue} onChange={setRadioValue} options={[{ value: "week", label: "Неделя" }, { value: "month", label: "Месяц" }, { value: "year", label: "Год", disabled: true }]} /></div></div>
              <div className="max-w-sm"><DateField label="Дата" value={date} onChange={(event) => setDate(event.target.value)} helperText="Можно открыть календарь" /></div>
              <div className="max-w-md"><DateRangeField fromValue={fromDate} toValue={toDate} onFromChange={setFromDate} onToChange={setToDate} /></div>
              <div className="max-w-sm"><DateField label="Ошибка даты" error="Дата вне диапазона" value="99.99.2026" readOnly /></div>
              <div className="max-w-sm"><DateField label="Дата недоступна" value="23.10.2026" disabled /></div>
            </div>
          </ShowcaseSection>

          <ShowcaseSection id="states" title="Состояния и аватары" description="Пустые списки, сбой, скелетон, спиннер и идентикон.">
            <div className="grid gap-4 lg:grid-cols-2">
              <EmptyState title="Нет записей" description="Пустое состояние с действием." action={<Button size="sm" onClick={() => setNotice("Нажато действие пустого состояния")}>Добавить запись</Button>} />
              <ErrorState title="Не удалось загрузить" description="Ошибка с возможностью повтора." action={<Button size="sm" variant="secondary" onClick={() => setNotice("Повторная попытка")}>Повторить</Button>} />
            </div>
            <div className="mt-5 flex flex-wrap items-center gap-6"><div><DemoLabel>Skeleton</DemoLabel><div className="space-y-2"><Skeleton className="h-6 w-48" /><Skeleton className="h-16 w-64" /></div></div><div><DemoLabel>Spinner</DemoLabel><div className="flex gap-3"><Spinner size="sm" /><Spinner size="md" /><Spinner size="lg" /></div></div><div><DemoLabel>AbstractAvatar</DemoLabel><div className="flex gap-3"><CompanyIdenticonAvatar seed="ПУЛЬС" size={40} /><CompanyIdenticonAvatar seed="ООО Маяк" size={40} /></div></div></div>
          </ShowcaseSection>

          <ShowcaseSection id="cards" title="Карточки и сигналы" description="Базовые и составные карточки, метрики и мини-графики.">
            <div className="grid gap-4 md:grid-cols-3"><Card title="Card" className="p-5">Обычная карточка</Card><Card variant="text" title="Text">Текстовая карточка</Card><Card variant="kpi" title="KPI">Контрастная карточка</Card></div>
            <div className="mt-4 grid gap-4 lg:grid-cols-2"><LayeredCard title="LayeredCard" top="Верхний слой" middle={<strong>Средний слой</strong>} bottom="Нижний слой" /><SplitCard leftTitle="Левая часть" rightTitle="Правая часть" left="Описание слева" right="Описание справа" /></div>
            <div className="mt-4"><KpiCardGroup columns={3}><KpiCard label="Поступления" value="120 000 ₽" caption="Тестовое значение" /><KpiCard label="Расходы" value="74 000 ₽" caption="Тестовое значение" /><KpiCard label="Остаток" value="46 000 ₽" caption="Тестовое значение" /></KpiCardGroup></div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3"><MetricTile label="Оборот" value="120 000 ₽" hint="Тестовые данные" change={8.4} color="var(--accent)" series={[20, 28, 24, 34, 40, 38, 48]} /><MetricTile label="Ошибки" value="3" change={-12} goodWhen="down" color="var(--danger)" series={[8, 7, 5, 6, 4, 3]} /><MetricTile label="Загрузка метрики" value="—" loading color="var(--accent)" /></div>
            <div className="mt-5 flex flex-wrap items-center gap-4"><TrendChip change={8.4} /><TrendChip change={-12} goodWhen="down" /><TrendChip change={null} /><div className="w-32"><Sparkline values={[2, 5, 4, 7, 9, 8]} color="var(--accent)" /></div><div className="w-32"><BarSparkline values={[2, 5, 4, 7, 9, 8]} color="var(--warning)" /></div></div>
            <div className="mt-5 grid gap-4 md:grid-cols-3">{mockSignals.map((signal) => <SignalCard key={signal.id} signal={signal} />)}</div>
          </ShowcaseSection>

          <ShowcaseSection id="tables" title="Таблицы и пагинация" description="Сортировка, заполненные строки и управление страницами.">
            <DemoLabel>MinimalSortableTable</DemoLabel>
            <MinimalSortableTable<OperationRow> data={operations} columns={tableColumns} rowKey={(row) => row.id} pagination={{ page: tablePage, totalPages: 2, pageSize: 2, onPageChange: setTablePage }} />
            <div className="mt-6"><DemoLabel>Составные части Table</DemoLabel><Table><TableHeader><TableRow><TableHead>Поле</TableHead><TableHead>Состояние</TableHead></TableRow></TableHeader><TableBody><TableRow><TableCell>Источник</TableCell><TableCell>Подключён</TableCell></TableRow><TableRow><TableCell>Прогноз</TableCell><TableCell>Ожидает</TableCell></TableRow></TableBody></Table></div>
            <div className="mt-5"><DemoLabel>Pagination</DemoLabel><div className="flex flex-wrap gap-6"><Pagination page={page} totalPages={5} onPageChange={setPage} /><Pagination page={1} totalPages={5} disabled onPageChange={() => undefined} /></div></div>
          </ShowcaseSection>

          <ShowcaseSection id="charts" title="Графики" description="Четыре вида графиков и их состояния на моковых значениях.">
            <div className="grid gap-4 xl:grid-cols-2"><ChartCard title="LineChart" description="Две серии"><LineChart data={chartData} xKey="date" series={chartSeries} /></ChartCard><ChartCard title="AreaChart" description="Две серии"><AreaChart data={chartData} xKey="date" series={chartSeries} /></ChartCard><ChartCard title="BarChart" description="Выбор столбца"><BarChart data={chartData} xKey="date" series={[chartSeries[0]]} title="Поступления" /></ChartCard><DonutChart data={donutData} title="DonutChart" metricLabel="Всего" colors={["var(--chart-series-emerald)", "var(--chart-series-amber)", "var(--chart-series-primary)"]} /></div>
            <div className="mt-4 grid gap-4 xl:grid-cols-3"><ChartCard title="Загрузка" contentClassName="h-72"><LineChart data={[]} xKey="date" series={chartSeries} loading /></ChartCard><ChartCard title="Пустой график"><ChartEmptyState title="Нет данных для графика" /></ChartCard><ChartCard title="Вспомогательные элементы" description="Legend и Tooltip"><ChartLegend payload={[{ value: "Поступления", dataKey: "income", color: "var(--accent)" }]} /><div className="mt-5"><ChartTooltip active label="01.11" payload={[{ name: "Поступления", value: 42, dataKey: "income", color: "var(--accent)" }]} /></div></ChartCard></div>
            <div className="mt-4 grid gap-4 xl:grid-cols-2"><ChartCard title="AreaChart · пусто"><AreaChart data={[]} xKey="date" series={chartSeries} isEmpty /></ChartCard><ChartCard title="BarChart · загрузка"><BarChart data={[]} xKey="date" series={[chartSeries[0]]} loading /></ChartCard></div>
          </ShowcaseSection>

          <ShowcaseSection id="finance" title="Финансовые блоки" description="Прогноз, параметры сценария и три состояния риска. Данные вымышлены.">
            <ChartCard title="CashflowForecastChart" description="Факт, базовый и негативный сценарий, события, границы и зона дефицита" contentClassName="h-80"><CashflowForecastChart days={cashflowDays} height={320} showBounds /></ChartCard>
            <div className="mt-4 grid items-start gap-4 lg:grid-cols-2"><ScenarioControls value={scenario} onChange={setScenario} /><ScenarioControls value={scenario} onChange={setScenario} loading /></div>
            <div className="mt-4 grid gap-4 lg:grid-cols-3"><RiskCard risk={mockRisk} onOpenScenario={() => document.getElementById("finance")?.scrollIntoView({ behavior: "smooth" })} /><RiskCard risk={null} status="clear" /><RiskCard risk={null} /></div>
          </ShowcaseSection>

          <ShowcaseSection id="layout" title="Составные блоки" description="CabinetShell, Sidebar, PageLayout и SectionCard используются в интерфейсе.">
            <div className="space-y-5"><PageHeader title="PageHeader · hero" description="Пример заголовка с бейджем и действием." variant="hero" headingLevel={2} badge={<Badge variant="brand">Активно</Badge>} actions={<Button size="sm" onClick={() => setNotice("Нажато действие заголовка")}>Действие <ArrowRight size={14} /></Button>} /><PageHeader title="PageHeader · compact" description="Компактный вариант заголовка с возвратом." variant="compact" headingLevel={2} backButton={{ href: "/", ariaLabel: "Вернуться к обзору" }} /><div><DemoLabel>Tabs</DemoLabel><Tabs tabs={[{ key: "overview", label: "Обзор", content: <p>Содержимое первой вкладки</p> }, { key: "details", label: "Детали", content: <p>Содержимое второй вкладки</p> }, { key: "disabled", label: "Недоступно", content: null, disabled: true }]} defaultValue="overview" /></div><div><DemoLabel>Stepper: обычный и ответвление</DemoLabel><div className="grid gap-4 lg:grid-cols-2"><Stepper steps={[{ key: "upload", label: "Загрузка" }, { key: "review", label: "Проверка" }, { key: "ready", label: "Готово" }]} currentKey="review" /><Stepper steps={[{ key: "upload", label: "Загрузка" }, { key: "review", label: "Проверка" }, { key: "ready", label: "Готово" }]} currentKey="review" branchLabel="Отклонено" /></div></div><div className="flex items-center gap-2"><span>InfoHint</span><InfoHint text="Пример справки с пояснением поведения компонента." /></div></div>
          </ShowcaseSection>

          <ShowcaseSection id="dialogs" title="Диалоги" description="Обычный, подтверждение и модальная форма. Нажмите кнопку, чтобы открыть пример.">
            <div className="flex flex-wrap gap-3"><Button onClick={() => setModal("dialog")}>Dialog</Button><Button variant="danger" onClick={() => setModal("confirm")}><Trash2 size={16} /> ConfirmDialog</Button><Button variant="secondary" onClick={() => setModal("form")}>FormModal</Button></div>
            <Dialog open={modal === "dialog"} title="Тестовый диалог" description="Содержимое обычного диалога" onClose={() => setModal(null)}><p>Диалог закрывается кнопкой, Escape или кликом вне панели.</p><div className="mt-5 flex justify-end"><Button onClick={() => setModal(null)}>Закрыть</Button></div></Dialog>
            <ConfirmDialog open={modal === "confirm"} title="Подтвердить действие?" description="Это только демонстрация, данные не меняются." confirmText="Подтвердить" onCancel={() => setModal(null)} onConfirm={() => { setModal(null); setNotice("Действие подтверждено на тестовой странице"); }} />
            <FormModal open={modal === "form"} title="Тестовая форма" description="Ввод останется только на этой странице." onClose={() => setModal(null)}><div className="space-y-4"><Input label="Название" value={name} onChange={(event) => setName(event.target.value)} /><div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => setModal(null)}>Отмена</Button><Button onClick={() => { setModal(null); setNotice("Тестовая форма сохранена локально"); }}>Сохранить</Button></div></div></FormModal>
          </ShowcaseSection>
        </div>
    </PageLayout>
  );
}

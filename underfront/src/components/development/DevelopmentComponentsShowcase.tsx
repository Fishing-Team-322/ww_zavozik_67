"use client";

import { useState, type ReactNode } from "react";
import { ArrowRight, Code2, LayoutGrid, PenLine, Plus } from "lucide-react";
import { PageLayout, SectionCard } from "@/src/components/cabinet/shared";
import { Breadcrumbs, Button, DateField, Input, SearchInput, Select, Tabs, Textarea } from "@/src/components/ui";

const buttonVariants = [
  { variant: "default", label: "Основная" },
  { variant: "secondary", label: "Вторичная" },
  { variant: "outline", label: "С обводкой" },
  { variant: "danger", label: "Опасная" },
  { variant: "ghost", label: "Текстовая" },
] as const;

const selectOptions = [
  { value: "retail", label: "Розничные продажи" },
  { value: "services", label: "Услуги" },
  { value: "production", label: "Производство" },
  { value: "archived", label: "Архивный вариант", disabled: true },
];

function ShowcaseBlock({ id, title, description, children }: { id: string; title: string; description: string; children: ReactNode }) {
  return (
    <SectionCard id={id} className="scroll-mt-20 p-5 sm:p-6">
      <h2 className="text-xl font-semibold text-[color:var(--text-primary)]">{title}</h2>
      <p className="mt-1 mb-5 text-sm text-[color:var(--text-secondary)]">{description}</p>
      {children}
    </SectionCard>
  );
}

function ExampleLabel({ children }: { children: ReactNode }) {
  return <p className="mb-2 text-xs font-medium text-[color:var(--text-secondary)]">{children}</p>;
}

export function DevelopmentComponentsShowcase() {
  const [notice, setNotice] = useState("");
  const [name, setName] = useState("ООО «Маяк»");
  const [search, setSearch] = useState("");
  const [date, setDate] = useState("23.10.2026");
  const [category, setCategory] = useState("retail");
  const [tab, setTab] = useState("overview");
  const tabs = [
    { key: "overview", label: "Обзор", content: <p className="text-sm text-[color:var(--text-secondary)]">Здесь показано содержимое первой вкладки на тестовых данных.</p> },
    { key: "details", label: "Детали", content: <p className="text-sm text-[color:var(--text-secondary)]">Здесь показано содержимое второй вкладки.</p> },
    { key: "disabled", label: "Недоступно", content: null, disabled: true },
  ];

  return (
    <PageLayout>
        <div className="space-y-6">
          <nav aria-label="Компоненты на странице" className="flex flex-wrap gap-x-5 gap-y-2 text-sm font-medium text-[color:var(--accent)]">
            <a href="#breadcrumbs">Breadcrumbs</a>
            <a href="#buttons">Кнопки</a>
            <a href="#inputs">Инпуты</a>
            <a href="#selects">Селект</a>
            <a href="#textareas">Многострочное поле</a>
            <a href="#tabs">Табы</a>
          </nav>
          <p aria-live="polite" className="min-h-5 text-sm text-[color:var(--text-secondary)]">{notice}</p>

          <ShowcaseBlock id="breadcrumbs" title="Breadcrumbs" description="Каждый уровень содержит иконку и название; между уровнями стоит шеврон вправо.">
            <div className="space-y-5">
              <div>
                <ExampleLabel>Раздел и страница</ExampleLabel>
                <Breadcrumbs items={[
                  { label: "Разработка", icon: Code2 },
                  { label: "Кнопки и поля", icon: LayoutGrid },
                ]} />
              </div>
              <div>
                <ExampleLabel>Вложенная страница</ExampleLabel>
                <Breadcrumbs items={[
                  { label: "Разработка", icon: Code2 },
                  { label: "Кнопки и поля", icon: LayoutGrid, href: "/development/components" },
                  { label: "Поля ввода", icon: PenLine },
                ]} />
              </div>
            </div>
          </ShowcaseBlock>

          <ShowcaseBlock id="buttons" title="Кнопки" description="Варианты, размеры, иконки и недоступное состояние.">
            <ExampleLabel>Варианты</ExampleLabel>
            <div className="flex flex-wrap items-center gap-3">
              {buttonVariants.map(({ variant, label }) => (
                <Button key={variant} variant={variant} onClick={() => setNotice(`Нажата кнопка «${label}»`)}>{label}</Button>
              ))}
              <Button variant="back" aria-label="Кнопка назад" onClick={() => setNotice("Нажата кнопка «Назад»")} />
            </div>
            <div className="mt-5 grid gap-5 lg:grid-cols-2">
              <div>
                <ExampleLabel>Размеры и иконка</ExampleLabel>
                <div className="flex flex-wrap items-center gap-3">
                  <Button size="sm">Малая</Button>
                  <Button size="md">Обычная</Button>
                  <Button size="lg">Большая</Button>
                  <Button size="icon" aria-label="Добавить" onClick={() => setNotice("Нажата кнопка с иконкой")}><Plus aria-hidden="true" /></Button>
                  <Button variant="outline" onClick={() => setNotice("Нажата кнопка с иконкой и текстом")}>Продолжить <ArrowRight aria-hidden="true" /></Button>
                </div>
              </div>
              <div>
                <ExampleLabel>Состояния</ExampleLabel>
                <div className="flex flex-wrap items-center gap-3">
                  <Button loading>Загрузка</Button>
                  <Button disabled>Недоступна</Button>
                  <Button variant="outline" disabled>Недоступна с обводкой</Button>
                </div>
              </div>
            </div>
          </ShowcaseBlock>

          <ShowcaseBlock id="inputs" title="Инпуты" description="Пустое и заполненное поле, ошибка, пароль, поиск и дата.">
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              <Input label="Пустое поле" placeholder="Введите название" />
              <Input label="Заполненное поле" value={name} onChange={(event) => setName(event.target.value)} helperText="Значение можно изменить" />
              <Input label="Ошибка" type="email" defaultValue="ошибка@" error="Введите корректный адрес" />
              <Input label="Недоступное поле" value="Только для просмотра" disabled readOnly />
              <Input label="Пароль" defaultValue="example-secret" secretToggle />
              <SearchInput label="Поиск" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Найти запись" />
              <Input label="Малый размер" inputSize="sm" defaultValue="Размер sm" />
              <Input label="Большой размер" inputSize="lg" defaultValue="Размер lg" />
              <DateField label="Дата" value={date} onChange={(event) => setDate(event.target.value)} />
            </div>
          </ShowcaseBlock>

          <ShowcaseBlock id="selects" title="Селект" description="Обычный выбор, поиск, ошибка и недоступное состояние.">
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              <Select label="Категория" options={selectOptions} value={category} onChange={(event) => setCategory(event.target.value)} />
              <Select label="С поиском" options={selectOptions} searchable placeholder="Выберите категорию" />
              <Select label="Без значения" options={selectOptions} placeholder="Выберите категорию" />
              <Select label="Ошибка выбора" options={selectOptions} error="Выберите категорию" />
              <Select label="Недоступный выбор" options={selectOptions} disabled />
              <Select label="Пустой список" options={[]} searchable emptyTitle="Вариантов нет" />
            </div>
          </ShowcaseBlock>

          <ShowcaseBlock id="textareas" title="Многострочное поле" description="Textarea использует цвета, рамку и скругление обычного инпута.">
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              <Textarea label="Пустое поле" placeholder="Введите комментарий" />
              <Textarea label="Заполненное поле" defaultValue="Пример текста для многострочного поля." helperText="Текст можно изменить" />
              <Textarea label="Ошибка" defaultValue="Коротко" error="Добавьте подробное описание" />
              <Textarea label="Недоступное поле" value="Только для просмотра" disabled readOnly />
            </div>
          </ShowcaseBlock>

          <ShowcaseBlock id="tabs" title="Табы" description="Переключение вкладок и недоступная вкладка.">
            <Tabs tabs={tabs} value={tab} onValueChange={setTab} />
            <div className="mt-6 grid gap-5 md:grid-cols-2">
              <div><ExampleLabel>Малый размер</ExampleLabel><Tabs tabs={tabs} size="sm" defaultValue="overview" showContent={false} /></div>
              <div><ExampleLabel>Большой размер</ExampleLabel><Tabs tabs={tabs} size="lg" defaultValue="details" showContent={false} /></div>
            </div>
          </ShowcaseBlock>
        </div>
    </PageLayout>
  );
}

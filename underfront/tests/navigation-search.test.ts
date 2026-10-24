import test from "node:test";
import assert from "node:assert/strict";
import { searchNavigation } from "../src/entities/navigation/model/search-navigation";

const items = [
  { label: "Обзор", href: "/overview" },
  { label: "Прогноз", href: "/forecast" },
  { label: "План-факт", href: "/plan-fact" },
  { label: "Платёжный календарь", href: "/calendar" },
  { label: "Налоги", href: "/taxes" },
  { label: "Настройки", href: "/settings" },
];

test("header search filters actual navigation instead of returning fixed demo results", () => {
  assert.deepEqual(searchNavigation(items, "  НАЛОГ  "), [items[4]]);
  assert.deepEqual(searchNavigation(items, "Настр"), [items[5]]);
  assert.deepEqual(searchNavigation(items, "неизвестный раздел"), []);
});

test("search treats е/ё, hyphens and spaces consistently and supports multiple words", () => {
  assert.deepEqual(searchNavigation(items, "платежный"), [items[3]]);
  assert.deepEqual(searchNavigation(items, "календарь   платёж"), [items[3]]);
  assert.deepEqual(searchNavigation(items, "план факт"), [items[2]]);
  assert.deepEqual(searchNavigation(items, "план-факт"), [items[2]]);
});

test("empty queries and empty navigation have no results", () => {
  for (const query of ["", "   ", "---", "?!"]) assert.deepEqual(searchNavigation(items, query), []);
  assert.deepEqual(searchNavigation([], "Прогноз"), []);
});

test("search respects custom navigation and excludes disabled, development and external links", () => {
  const visible = { label: "Новый отчёт", href: "/custom-report", section: "Дополнительно" };
  const navigation = [
    { label: "Новый отчёт: закрыт", href: "/disabled", disabled: true },
    { label: "Новый отчёт: демо", href: "/test", section: "Development" },
    { label: "Новый отчёт: разработка", href: "/development/components", section: "Разработка" },
    { label: "Новый отчёт: внешний", href: "https://example.invalid/report" },
    { label: "Новый отчёт: другой сайт", href: "//example.invalid/report" },
    visible,
    { ...visible },
  ];
  assert.deepEqual(searchNavigation(navigation, "отчет"), [visible]);
});

test("matches preserve navigation order and do not mutate the navigation", () => {
  const navigation = Object.freeze(items.map(item => Object.freeze({ ...item })));
  const result = searchNavigation(navigation, "п");
  assert.deepEqual(result, [navigation[1], navigation[2], navigation[3]]);
  assert.equal(result[0], navigation[1]);
  assert.equal(navigation.length, items.length);
});

"use client";

import { useCallback, useEffect, useState } from "react";
import { api, message } from "./client";

/** Scope changes and canceled requests cannot expose another company's previous response. */
export function useApiResource<T>(
  path: string | null,
  options: { method?: string; json?: unknown } = {},
) {
  const payload =
    options.json === undefined ? undefined : JSON.stringify(options.json);
  const method = options.method || "GET";
  const key = `${path}\n${method}\n${payload}`;
  const [version, setVersion] = useState(0);
  useEffect(() => api.onDataChanged(() => setVersion(value => value + 1)), []);
  const [state, setState] = useState<{
    key: string;
    data: T | null;
    error: string | null;
    loading: boolean;
  }>({ key: "", data: null, error: null, loading: false });
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    const timer = setTimeout(
      () => {
        setState((previous) => ({
          key,
          data: previous.key === key ? previous.data : null,
          error: null,
          loading: true,
        }));
        api
          .request<T>(path, {
            method,
            json: payload === undefined ? undefined : JSON.parse(payload),
            signal: controller.signal,
          })
          .then((data) => {
            if (!controller.signal.aborted)
              setState({ key, data, error: null, loading: false });
          })
          .catch((error) => {
            if (!controller.signal.aborted)
              setState({
                key,
                data: null,
                error: message(error),
                loading: false,
              });
          });
      },
      method === "GET" ? 0 : 300,
    );
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [path, payload, method, key, version]);
  const current =
    path && state.key === key
      ? state
      : { data: null, error: null, loading: !!path };
  const refresh = useCallback(() => setVersion(value => value + 1), []);
  return { ...current, refresh };
}

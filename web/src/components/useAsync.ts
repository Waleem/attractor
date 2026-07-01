import { useCallback, useEffect, useState, type DependencyList } from "react";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
  setData: (value: T | null) => void;
}

export function useAsync<T>(loader: () => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshToken, setRefreshToken] = useState(0);

  const refresh = useCallback(() => setRefreshToken((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    loader()
      .then((value) => {
        if (!active) {
          return;
        }
        setData(value);
      })
      .catch((caught: unknown) => {
        if (!active) {
          return;
        }
        setError(caught instanceof Error ? caught.message : String(caught));
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [...deps, refreshToken]);

  return { data, error, loading, refresh, setData };
}

import { useEffect, useRef, useState, type CSSProperties } from "react";

interface Props {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  style?: CSSProperties;
  list?: string;
  delay?: number;
  type?: string;
}

/** Controlled text input that debounces upstream onChange (for URL-bound filters/search). */
export default function DebouncedInput({ value, onChange, placeholder, style, list, delay = 300, type = "text" }: Props) {
  const [local, setLocal] = useState(value);
  const touched = useRef(false);

  // keep in sync when the URL value changes externally (e.g. Clear all)
  useEffect(() => { if (!touched.current) setLocal(value); }, [value]);

  useEffect(() => {
    if (!touched.current) return;
    const id = setTimeout(() => { onChange(local); touched.current = false; }, delay);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [local]);

  return (
    <input
      type={type}
      value={local}
      list={list}
      placeholder={placeholder}
      onChange={(e) => { touched.current = true; setLocal(e.target.value); }}
      style={style}
    />
  );
}

import { useEffect, useRef, useState, type CSSProperties } from "react";

interface Props {
  src: string | null | undefined;
  alt?: string;
  style?: CSSProperties;
  fit?: "cover" | "contain";
  position?: string;
  fallbackLabel?: string;
  className?: string;
  loading?: "eager" | "lazy";
}

/** <img> with a graceful broken/expired fallback (FB CDN creatives can 403). */
export default function SafeImage({ src, alt = "", style, fit = "cover", position = "center", fallbackLabel = "Image unavailable", className, loading = "lazy" }: Props) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [recoveringSrc, setRecoveringSrc] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<{ source: string; url: string } | null>(null);
  const recoveryAbort = useRef<AbortController | null>(null);
  const recoveryObjectUrl = useRef<string | null>(null);
  const broken = !!src && failedSrc === src;
  const recovering = !!src && recoveringSrc === src;
  const displaySrc = recovery && recovery.source === src ? recovery.url : src;

  useEffect(() => {
    recoveryAbort.current?.abort();
    recoveryAbort.current = null;
    if (recoveryObjectUrl.current) {
      URL.revokeObjectURL(recoveryObjectUrl.current);
      recoveryObjectUrl.current = null;
    }
    setFailedSrc(null);
    setRecoveringSrc(null);
    setRecovery(null);

    return () => {
      recoveryAbort.current?.abort();
      if (recoveryObjectUrl.current) {
        URL.revokeObjectURL(recoveryObjectUrl.current);
        recoveryObjectUrl.current = null;
      }
    };
  }, [src]);

  const recoverProtectedMedia = async (source: string) => {
    if (recoveringSrc === source) return;
    const controller = new AbortController();
    recoveryAbort.current?.abort();
    recoveryAbort.current = controller;
    setRecoveringSrc(source);

    try {
      const blob = await fetchProtectedImage(source, controller.signal);
      if (controller.signal.aborted) return;
      const objectUrl = URL.createObjectURL(blob);
      if (recoveryObjectUrl.current) URL.revokeObjectURL(recoveryObjectUrl.current);
      recoveryObjectUrl.current = objectUrl;
      setRecovery({ source, url: objectUrl });
      setFailedSrc(null);
    } catch (error) {
      if (!controller.signal.aborted) setFailedSrc(source);
    } finally {
      if (!controller.signal.aborted) setRecoveringSrc(null);
    }
  };

  if (!src || broken || recovering) {
    return (
      <div
        className={className}
        style={{
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8,
          background: "repeating-conic-gradient(#EEF2F0 0% 25%,#F6F9F7 0% 50%) 50%/18px 18px",
          color: "#8A938E", textAlign: "center", ...style,
        }}
      >
        <span style={{ fontSize: 26 }}>🚫</span>
        <span style={{ fontSize: 11.5, fontWeight: 600, padding: "0 10px" }}>{recovering ? "Loading media..." : fallbackLabel}</span>
      </div>
    );
  }
  return (
    <img
      className={className}
      src={displaySrc || undefined}
      alt={alt}
      loading={loading}
      onError={() => {
        if (isProtectedMediaUrl(src) && recovery?.source !== src) {
          void recoverProtectedMedia(src);
          return;
        }
        setFailedSrc(src);
      }}
      style={{ objectFit: fit, objectPosition: position, ...style }}
    />
  );
}

function isProtectedMediaUrl(value: string): boolean {
  try {
    const url = new URL(value, window.location.origin);
    return url.origin === window.location.origin && url.pathname.startsWith("/media/");
  } catch {
    return false;
  }
}

async function fetchProtectedImage(source: string, signal: AbortSignal): Promise<Blob> {
  let lastError: Error = new Error("Media recovery failed");
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const url = new URL(source, window.location.origin);
      if (attempt > 0) url.searchParams.set("_retry", String(attempt));
      const response = await fetch(url, {
        credentials: "same-origin",
        cache: attempt === 0 ? "default" : "reload",
        signal,
      });
      if (!response.ok) throw new Error(`Media recovery failed: ${response.status}`);
      const blob = await response.blob();
      if (blob.size <= 0 || !blob.type.startsWith("image/")) {
        throw new Error("Media recovery returned an invalid image");
      }
      return blob;
    } catch (error) {
      if (signal.aborted) throw error;
      lastError = error instanceof Error ? error : lastError;
      if (attempt === 0) await new Promise((resolve) => window.setTimeout(resolve, 350));
    }
  }
  throw lastError;
}

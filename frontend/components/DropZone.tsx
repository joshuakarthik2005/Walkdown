"use client";
// Secondary input: drop your own walkdown video or photos.
import { useState } from "react";

export function DropZone({
  files,
  maxMb,
  maxSeconds,
  busy,
  onFiles,
}: {
  files: File[];
  maxMb: number | null;
  maxSeconds: number | null;
  busy: boolean;
  onFiles: (f: File[]) => void;
}) {
  const [over, setOver] = useState(false);
  const limits = maxMb ? `MP4/MOV up to ${maxMb} MB${maxSeconds ? ` and ${maxSeconds} s` : ""}, or JPG/PNG photos` : "MP4/MOV video, or JPG/PNG photos";
  return (
    <label
      className={`dropzone${over ? " over" : ""}${files.length ? " has-files" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!busy) onFiles(Array.from(e.dataTransfer.files));
      }}
    >
      <input
        type="file"
        multiple
        accept="video/mp4,video/quicktime,image/jpeg,image/png"
        disabled={busy}
        onChange={(e) => onFiles(Array.from(e.target.files ?? []))}
      />
      {files.length ? (
        <span>
          <b>{files.length === 1 ? files[0].name : `${files.length} photos`}</b> selected · <span className="link">change</span>
        </span>
      ) : (
        <span>
          <b>Or upload your own walkdown</b>: drop a file here or <span className="link">browse</span>
        </span>
      )}
      <span className="muted small">{limits}</span>
    </label>
  );
}

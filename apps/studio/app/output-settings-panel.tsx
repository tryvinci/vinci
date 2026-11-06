"use client";

type Props = {
  outputDestKind: string;
  setOutputDestKind: (value: string) => void;
  outputLocalDir: string;
  setOutputLocalDir: (value: string) => void;
  outputPhotosAlbum: string;
  setOutputPhotosAlbum: (value: string) => void;
  outputR2Prefix: string;
  setOutputR2Prefix: (value: string) => void;
  outputR2Configured: boolean;
  onSave: () => Promise<void>;
};

/** Output destination controls (Roadmap PR #1). Lives on Settings, not Connect. */
export function OutputSettingsPanel(props: Props) {
  return (
    <div className="connect-routing" data-testid="output-destination-settings">
      <p className="eyebrow">Where files are saved</p>
      <p className="muted">After each finished run, also copy the file. Bucket keys come from the environment only.</p>
      <label htmlFor="output-dest-kind">Save to</label>
      <select
        id="output-dest-kind"
        value={props.outputDestKind}
        onChange={(ev) => props.setOutputDestKind(ev.target.value)}
      >
        <option value="none">Keep in the app</option>
        <option value="local">Local folder</option>
        <option value="photos">Photos album</option>
        <option value="r2">Bucket</option>
      </select>
      {props.outputDestKind === "local" ? (
        <>
          <label htmlFor="output-local-dir">Folder path</label>
          <input
            id="output-local-dir"
            value={props.outputLocalDir}
            onChange={(ev) => props.setOutputLocalDir(ev.target.value)}
            placeholder="~/Pictures/Vinci"
          />
        </>
      ) : null}
      {props.outputDestKind === "photos" ? (
        <>
          <label htmlFor="output-photos-album">Album name</label>
          <input
            id="output-photos-album"
            value={props.outputPhotosAlbum}
            onChange={(ev) => props.setOutputPhotosAlbum(ev.target.value)}
            placeholder="Vinci"
          />
          <p className="muted">
            The Mac app imports into Photos from the file menu.
          </p>
        </>
      ) : null}
      {props.outputDestKind === "r2" ? (
        <>
          <label htmlFor="output-r2-prefix">Folder prefix</label>
          <input
            id="output-r2-prefix"
            value={props.outputR2Prefix}
            onChange={(ev) => props.setOutputR2Prefix(ev.target.value)}
            placeholder="vinci/outputs/"
          />
          <p className="muted">
            {props.outputR2Configured
              ? "Bucket keys found."
              : "Add the bucket name and keys in the environment, then restart."}
          </p>
        </>
      ) : null}
      <button className="ghost" type="button" onClick={() => void props.onSave()}>
        Save
      </button>
    </div>
  );
}

//! Fast, auditable filesystem operations for Codec Carver audio libraries.

use std::cmp::Ordering;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::LazyLock;
use std::time::{SystemTime, UNIX_EPOCH};

#[cfg(target_os = "macos")]
use std::os::macos::fs::MetadataExt;

use anyhow::{Context, Result, anyhow, bail};
use chrono::{DateTime, Local, NaiveDate, TimeZone};
use rayon::prelude::*;
use regex::Regex;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use unicode_normalization::UnicodeNormalization;
use walkdir::{DirEntry, WalkDir};

static COMPACT_TIME_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?P<yy>\d{2})(?P<month>\d{2})(?P<day>\d{2})[_-](?P<hour>\d{2})(?P<minute>\d{2})")
        .expect("valid compact timestamp regex")
});
static ISO_TIME_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?P<iso>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))")
        .expect("valid ISO timestamp regex")
});
static COPY_SUFFIX_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)(?:\s*\(\d+\)|\s+\d+)$").expect("valid copy suffix regex"));
static TMK_MARK_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\[(?P<minutes>\d{5}):(?P<seconds>\d{2})\.(?P<hundredths>\d{2})\]")
        .expect("valid TMK regex")
});
static ADDRESS_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[가-힣0-9]+(?:동|가|로|길)(?:\s*[0-9-]+)?").expect("valid Korean address regex")
});

const AUDIO_EXTENSIONS: &[&str] = &["wav", "m4a", "mp3", "flac", "aac", "opus", "ogg", "wma"];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct FileRecord {
    pub path: String,
    pub kind: FileKind,
    pub extension: String,
    pub size_bytes: u64,
    pub materialized: bool,
    pub sha256: Option<String>,
    pub recorded_at: Option<String>,
    pub time_source: Option<TimeSource>,
    pub location: Option<String>,
    pub tmk_path: Option<String>,
    pub tmk_marker_count: Option<usize>,
    pub tmk_last_marker_seconds: Option<f64>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FileKind {
    Audio,
    Tmk,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TimeSource {
    IsoFilename,
    CompactFilename,
    FilesystemCreated,
    FilesystemModified,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DuplicateGroup {
    pub sha256: String,
    pub size_bytes: u64,
    pub canonical_path: String,
    pub duplicate_paths: Vec<String>,
    pub earliest_recorded_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InventoryManifest {
    pub schema_version: u32,
    pub root: String,
    pub generated_at: String,
    pub earliest_recording_at: Option<String>,
    pub audio_file_count: usize,
    pub tmk_file_count: usize,
    pub dataless_file_count: usize,
    pub total_audio_bytes: u64,
    pub files: Vec<FileRecord>,
    pub duplicate_groups: Vec<DuplicateGroup>,
    pub errors: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct StageResult {
    pub record: FileRecord,
    pub staged_path: String,
}

#[derive(Debug, Clone)]
struct PendingFile {
    absolute_path: PathBuf,
    relative_path: String,
    kind: FileKind,
    extension: String,
    size_bytes: u64,
    materialized: bool,
    recorded_at: Option<String>,
    time_source: Option<TimeSource>,
    location: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MutationPlan {
    pub schema_version: u32,
    pub root: String,
    pub operations: Vec<MutationOperation>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MutationOperation {
    pub action: MutationAction,
    pub source: String,
    pub destination: String,
    pub sha256: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MutationAction {
    Rename,
    Quarantine,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ApplyJournal {
    pub schema_version: u32,
    pub root: String,
    pub executed: bool,
    pub operation_count: usize,
    pub completed: Vec<MutationOperation>,
}

/// Scan, hash, and correlate an audio library.
pub fn inventory(root: &Path, threads: Option<usize>) -> Result<InventoryManifest> {
    let canonical_root = root
        .canonicalize()
        .with_context(|| format!("cannot resolve library root {}", root.display()))?;
    if !canonical_root.is_dir() {
        bail!(
            "library root is not a directory: {}",
            canonical_root.display()
        );
    }

    let mut pending = Vec::new();
    let mut errors = Vec::new();
    for entry in WalkDir::new(&canonical_root)
        .follow_links(false)
        .into_iter()
        .filter_entry(|entry| !is_excluded_entry(entry, &canonical_root))
    {
        let entry = match entry {
            Ok(value) => value,
            Err(error) => {
                errors.push(error.to_string());
                continue;
            }
        };
        if !entry.file_type().is_file() {
            continue;
        }
        let Some((kind, extension)) = classify(entry.path()) else {
            continue;
        };
        match pending_file(&canonical_root, entry.path(), kind, extension) {
            Ok(value) => pending.push(value),
            Err(error) => errors.push(error.to_string()),
        }
    }

    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(threads.unwrap_or_else(default_hash_threads).max(1))
        .build()
        .context("cannot create hashing thread pool")?;
    let mut files = pool.install(|| pending.par_iter().map(process_file).collect::<Vec<_>>());
    correlate_tmk(&mut files);
    files.sort_by(|left, right| left.path.cmp(&right.path));

    let duplicate_groups = find_duplicate_groups(&files);
    let earliest_recording_at = files
        .iter()
        .filter(|record| record.kind == FileKind::Audio)
        .filter_map(|record| record.recorded_at.clone())
        .min();
    let audio_file_count = files
        .iter()
        .filter(|record| record.kind == FileKind::Audio)
        .count();
    let tmk_file_count = files
        .iter()
        .filter(|record| record.kind == FileKind::Tmk)
        .count();
    let dataless_file_count = files.iter().filter(|record| !record.materialized).count();
    let total_audio_bytes = files
        .iter()
        .filter(|record| record.kind == FileKind::Audio)
        .map(|record| record.size_bytes)
        .sum();
    errors.extend(files.iter().filter_map(|record| {
        record
            .error
            .as_ref()
            .map(|error| format!("{}: {error}", record.path))
    }));

    Ok(InventoryManifest {
        schema_version: 1,
        root: canonical_root.to_string_lossy().nfc().collect(),
        generated_at: Local::now().to_rfc3339(),
        earliest_recording_at,
        audio_file_count,
        tmk_file_count,
        dataless_file_count,
        total_audio_bytes,
        files,
        duplicate_groups,
        errors,
    })
}

/// Produce JSON and optionally persist the inventory with an atomic rename.
pub fn inventory_to_json(
    root: &Path,
    output: Option<&Path>,
    threads: Option<usize>,
) -> Result<String> {
    let manifest = inventory(root, threads)?;
    let payload = serde_json::to_string_pretty(&manifest)?;
    if let Some(path) = output {
        atomic_write(path, payload.as_bytes())?;
    }
    Ok(payload)
}

/// Inspect one materialized file without rescanning or rehashing the library.
pub fn inspect_relative(root: &Path, relative_path: &Path) -> Result<FileRecord> {
    let canonical_root = root
        .canonicalize()
        .with_context(|| format!("cannot resolve library root {}", root.display()))?;
    validate_relative_path(&relative_path.to_string_lossy())?;
    let requested = canonical_root.join(relative_path);
    let canonical_path = requested
        .canonicalize()
        .with_context(|| format!("cannot resolve library file {}", requested.display()))?;
    if !canonical_path.starts_with(&canonical_root) {
        bail!("library file escaped root: {}", canonical_path.display());
    }
    let (kind, extension) = classify(&canonical_path)
        .ok_or_else(|| anyhow!("unsupported audio/TMK file: {}", canonical_path.display()))?;
    let pending = pending_file(&canonical_root, &canonical_path, kind, extension)?;
    Ok(process_file(&pending))
}

/// Inspect one file and serialize its stable record schema.
pub fn inspect_relative_to_json(root: &Path, relative_path: &Path) -> Result<String> {
    Ok(serde_json::to_string_pretty(&inspect_relative(
        root,
        relative_path,
    )?)?)
}

/// Stream one file into local scratch storage while computing its SHA-256 once.
pub fn stage_relative(
    root: &Path,
    relative_path: &Path,
    staging_dir: &Path,
) -> Result<StageResult> {
    let canonical_root = root
        .canonicalize()
        .with_context(|| format!("cannot resolve library root {}", root.display()))?;
    validate_relative_path(&relative_path.to_string_lossy())?;
    let requested = canonical_root.join(relative_path);
    let canonical_path = requested
        .canonicalize()
        .with_context(|| format!("cannot resolve library file {}", requested.display()))?;
    if !canonical_path.starts_with(&canonical_root) {
        bail!("library file escaped root: {}", canonical_path.display());
    }
    let (kind, extension) = classify(&canonical_path)
        .ok_or_else(|| anyhow!("unsupported audio/TMK file: {}", canonical_path.display()))?;
    let pending = pending_file(&canonical_root, &canonical_path, kind, extension.clone())?;

    fs::create_dir_all(staging_dir)
        .with_context(|| format!("cannot create staging directory {}", staging_dir.display()))?;
    let canonical_staging = staging_dir
        .canonicalize()
        .with_context(|| format!("cannot resolve staging directory {}", staging_dir.display()))?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let partial = canonical_staging.join(format!(
        ".codec-carver-{}-{nonce}.{extension}.partial",
        std::process::id()
    ));
    let mut tmk_bytes = (kind == FileKind::Tmk)
        .then(|| Vec::with_capacity(pending.size_bytes.min(1024 * 1024) as usize));
    let sha256 = match copy_and_hash_file(&canonical_path, &partial, tmk_bytes.as_mut()) {
        Ok(hash) => hash,
        Err(error) => {
            let _ = fs::remove_file(&partial);
            return Err(error);
        }
    };
    let staged_path = canonical_staging.join(format!("{sha256}.{extension}"));
    if staged_path.exists() {
        if hash_file(&staged_path, None)? == sha256 {
            fs::remove_file(&partial)?;
        } else {
            fs::remove_file(&staged_path)?;
            fs::rename(&partial, &staged_path)?;
        }
    } else {
        fs::rename(&partial, &staged_path)?;
    }
    let markers = tmk_bytes
        .as_deref()
        .map(parse_tmk_markers)
        .unwrap_or_default();
    Ok(StageResult {
        record: FileRecord {
            path: pending.relative_path,
            kind,
            extension,
            size_bytes: pending.size_bytes,
            materialized: pending.materialized,
            sha256: Some(sha256),
            recorded_at: pending.recorded_at,
            time_source: pending.time_source,
            location: pending.location,
            tmk_path: None,
            tmk_marker_count: (kind == FileKind::Tmk).then_some(markers.len()),
            tmk_last_marker_seconds: markers.last().copied(),
            error: None,
        },
        staged_path: staged_path.to_string_lossy().nfc().collect(),
    })
}

/// Stage one file and serialize its record plus scratch path.
pub fn stage_relative_to_json(
    root: &Path,
    relative_path: &Path,
    staging_dir: &Path,
) -> Result<String> {
    Ok(serde_json::to_string_pretty(&stage_relative(
        root,
        relative_path,
        staging_dir,
    )?)?)
}

fn is_excluded_entry(entry: &DirEntry, root: &Path) -> bool {
    if entry.path() == root {
        return false;
    }
    entry.file_type().is_dir()
        && matches!(
            entry.file_name().to_str(),
            Some(".git" | ".codec-carver" | "target" | ".venv")
        )
}

fn classify(path: &Path) -> Option<(FileKind, String)> {
    let extension = path.extension()?.to_string_lossy().to_ascii_lowercase();
    if AUDIO_EXTENSIONS.contains(&extension.as_str()) {
        Some((FileKind::Audio, extension))
    } else if extension == "tmk" {
        Some((FileKind::Tmk, extension))
    } else {
        None
    }
}

fn pending_file(
    root: &Path,
    path: &Path,
    kind: FileKind,
    extension: String,
) -> Result<PendingFile> {
    let metadata = fs::metadata(path).with_context(|| format!("cannot stat {}", path.display()))?;
    let relative_path: String = path
        .strip_prefix(root)
        .context("scanned path escaped root")?
        .to_string_lossy()
        .nfc()
        .collect();
    let filename: String = path
        .file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .nfc()
        .collect();
    let (recorded_at, time_source) = infer_recorded_at(&filename, &metadata);
    Ok(PendingFile {
        absolute_path: path.to_path_buf(),
        relative_path,
        kind,
        extension,
        size_bytes: metadata.len(),
        materialized: !is_dataless(&metadata),
        recorded_at,
        time_source,
        location: infer_location(&filename),
    })
}

fn process_file(pending: &PendingFile) -> FileRecord {
    let mut tmk_bytes = if pending.kind == FileKind::Tmk {
        Some(Vec::with_capacity(
            pending.size_bytes.min(1024 * 1024) as usize
        ))
    } else {
        None
    };
    let result = if pending.materialized {
        hash_file(&pending.absolute_path, tmk_bytes.as_mut())
    } else {
        Err(anyhow!(
            "iCloud dataless placeholder; materialize with `brctl download` before hashing"
        ))
    };
    let (sha256, error) = match result {
        Ok(hash) => (Some(hash), None),
        Err(error) => (None, Some(error.to_string())),
    };
    let markers = tmk_bytes
        .as_deref()
        .map(parse_tmk_markers)
        .unwrap_or_default();
    FileRecord {
        path: pending.relative_path.clone(),
        kind: pending.kind,
        extension: pending.extension.clone(),
        size_bytes: pending.size_bytes,
        materialized: pending.materialized,
        sha256,
        recorded_at: pending.recorded_at.clone(),
        time_source: pending.time_source,
        location: pending.location.clone(),
        tmk_path: None,
        tmk_marker_count: (pending.kind == FileKind::Tmk).then_some(markers.len()),
        tmk_last_marker_seconds: markers.last().copied(),
        error,
    }
}

#[cfg(target_os = "macos")]
fn is_dataless(metadata: &fs::Metadata) -> bool {
    const SF_DATALESS: u32 = 0x4000_0000;
    metadata.st_flags() & SF_DATALESS != 0
}

#[cfg(not(target_os = "macos"))]
fn is_dataless(_metadata: &fs::Metadata) -> bool {
    false
}

fn hash_file(path: &Path, capture: Option<&mut Vec<u8>>) -> Result<String> {
    let file = File::open(path).with_context(|| format!("cannot open {}", path.display()))?;
    let mut reader = BufReader::with_capacity(1024 * 1024, file);
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    let mut capture = capture;
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
        if let Some(bytes) = capture.as_deref_mut() {
            bytes.extend_from_slice(&buffer[..read]);
        }
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn copy_and_hash_file(
    source: &Path,
    destination: &Path,
    capture: Option<&mut Vec<u8>>,
) -> Result<String> {
    let input = File::open(source).with_context(|| format!("cannot open {}", source.display()))?;
    let output = File::create(destination)
        .with_context(|| format!("cannot create {}", destination.display()))?;
    let mut reader = BufReader::with_capacity(1024 * 1024, input);
    let mut writer = BufWriter::with_capacity(1024 * 1024, output);
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    let mut capture = capture;
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        writer.write_all(&buffer[..read])?;
        hasher.update(&buffer[..read]);
        if let Some(bytes) = capture.as_deref_mut() {
            bytes.extend_from_slice(&buffer[..read]);
        }
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(format!("{:x}", hasher.finalize()))
}

fn parse_tmk_markers(bytes: &[u8]) -> Vec<f64> {
    let text = String::from_utf8_lossy(bytes);
    TMK_MARK_RE
        .captures_iter(&text)
        .filter_map(|capture| {
            let minutes = capture.name("minutes")?.as_str().parse::<f64>().ok()?;
            let seconds = capture.name("seconds")?.as_str().parse::<f64>().ok()?;
            let hundredths = capture.name("hundredths")?.as_str().parse::<f64>().ok()?;
            Some(minutes * 60.0 + seconds + hundredths / 100.0)
        })
        .collect()
}

fn correlate_tmk(files: &mut [FileRecord]) {
    let mut exact = HashMap::new();
    let mut normalized = HashMap::new();
    for record in files.iter().filter(|record| record.kind == FileKind::Tmk) {
        let path = Path::new(&record.path);
        exact.insert(sidecar_key(path, false), record.path.clone());
        normalized
            .entry(sidecar_key(path, true))
            .or_insert_with(|| record.path.clone());
    }
    let tmk_details: HashMap<String, (Option<usize>, Option<f64>)> = files
        .iter()
        .filter(|record| record.kind == FileKind::Tmk)
        .map(|record| {
            (
                record.path.clone(),
                (record.tmk_marker_count, record.tmk_last_marker_seconds),
            )
        })
        .collect();
    for record in files
        .iter_mut()
        .filter(|record| record.kind == FileKind::Audio)
    {
        let path = Path::new(&record.path);
        let matched = exact
            .get(&sidecar_key(path, false))
            .or_else(|| normalized.get(&sidecar_key(path, true)));
        if let Some(tmk_path) = matched {
            record.tmk_path = Some(tmk_path.clone());
            if let Some((count, last)) = tmk_details.get(tmk_path) {
                record.tmk_marker_count = *count;
                record.tmk_last_marker_seconds = *last;
            }
        }
    }
}

fn sidecar_key(path: &Path, remove_copy_suffix: bool) -> String {
    let parent: String = path
        .parent()
        .unwrap_or_else(|| Path::new(""))
        .to_string_lossy()
        .nfc()
        .collect();
    let stem: String = path
        .file_stem()
        .unwrap_or_default()
        .to_string_lossy()
        .nfc()
        .collect();
    let stem = if remove_copy_suffix {
        COPY_SUFFIX_RE.replace(&stem, "").into_owned()
    } else {
        stem
    };
    format!("{parent}\0{}", stem.to_lowercase())
}

fn infer_recorded_at(
    filename: &str,
    metadata: &fs::Metadata,
) -> (Option<String>, Option<TimeSource>) {
    if let Some(capture) = ISO_TIME_RE.captures(filename)
        && let Some(raw) = capture.name("iso")
        && let Ok(value) = DateTime::parse_from_rfc3339(raw.as_str())
    {
        return (Some(value.to_rfc3339()), Some(TimeSource::IsoFilename));
    }
    if let Some(capture) = COMPACT_TIME_RE.captures(filename) {
        let parsed = (|| {
            let year = 2000 + capture.name("yy")?.as_str().parse::<i32>().ok()?;
            let month = capture.name("month")?.as_str().parse::<u32>().ok()?;
            let day = capture.name("day")?.as_str().parse::<u32>().ok()?;
            let hour = capture.name("hour")?.as_str().parse::<u32>().ok()?;
            let minute = capture.name("minute")?.as_str().parse::<u32>().ok()?;
            let naive = NaiveDate::from_ymd_opt(year, month, day)?.and_hms_opt(hour, minute, 0)?;
            Local.from_local_datetime(&naive).earliest()
        })();
        if let Some(value) = parsed {
            return (Some(value.to_rfc3339()), Some(TimeSource::CompactFilename));
        }
    }
    if let Ok(created) = metadata.created() {
        return (
            Some(system_time_to_rfc3339(created)),
            Some(TimeSource::FilesystemCreated),
        );
    }
    if let Ok(modified) = metadata.modified() {
        return (
            Some(system_time_to_rfc3339(modified)),
            Some(TimeSource::FilesystemModified),
        );
    }
    (None, None)
}

fn system_time_to_rfc3339(time: SystemTime) -> String {
    let value: DateTime<Local> = time.into();
    value.to_rfc3339()
}

fn infer_location(filename: &str) -> Option<String> {
    let stem = Path::new(filename).file_stem()?.to_string_lossy();
    let candidates: Vec<String> = stem
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .filter(|line| !ISO_TIME_RE.is_match(line))
        .filter(|line| ADDRESS_RE.is_match(line))
        .map(ToOwned::to_owned)
        .collect();
    let selected = candidates.last()?.trim();
    let normalized = COPY_SUFFIX_RE.replace(selected, "").trim().to_string();
    (!normalized.is_empty()).then_some(normalized)
}

fn find_duplicate_groups(files: &[FileRecord]) -> Vec<DuplicateGroup> {
    let mut by_hash: BTreeMap<&str, Vec<&FileRecord>> = BTreeMap::new();
    for record in files.iter().filter(|record| record.kind == FileKind::Audio) {
        if let Some(hash) = record.sha256.as_deref() {
            by_hash.entry(hash).or_default().push(record);
        }
    }
    by_hash
        .into_iter()
        .filter(|(_, records)| records.len() > 1)
        .map(|(hash, mut records)| {
            records.sort_by(|left, right| canonical_cmp(left, right));
            let canonical = records[0];
            let earliest_recorded_at = records
                .iter()
                .filter_map(|record| record.recorded_at.clone())
                .min();
            DuplicateGroup {
                sha256: hash.to_string(),
                size_bytes: canonical.size_bytes,
                canonical_path: canonical.path.clone(),
                duplicate_paths: records[1..]
                    .iter()
                    .map(|record| record.path.clone())
                    .collect(),
                earliest_recorded_at,
            }
        })
        .collect()
}

fn canonical_cmp(left: &FileRecord, right: &FileRecord) -> Ordering {
    let left_key = (
        left.recorded_at.as_deref().unwrap_or("9999"),
        COPY_SUFFIX_RE.is_match(
            Path::new(&left.path)
                .file_stem()
                .unwrap_or_default()
                .to_string_lossy()
                .as_ref(),
        ),
        left.tmk_path.is_none(),
        left.location.is_none(),
        left.path.matches('/').count(),
        left.path.as_str(),
    );
    let right_key = (
        right.recorded_at.as_deref().unwrap_or("9999"),
        COPY_SUFFIX_RE.is_match(
            Path::new(&right.path)
                .file_stem()
                .unwrap_or_default()
                .to_string_lossy()
                .as_ref(),
        ),
        right.tmk_path.is_none(),
        right.location.is_none(),
        right.path.matches('/').count(),
        right.path.as_str(),
    );
    left_key.cmp(&right_key)
}

fn default_hash_threads() -> usize {
    std::thread::available_parallelism()
        .map(usize::from)
        .unwrap_or(1)
        .min(8)
}

/// Validate a relative path used by a mutation plan.
pub fn validate_relative_path(path: &str) -> Result<()> {
    let value = Path::new(path);
    if value.as_os_str().is_empty() || value.is_absolute() {
        bail!("mutation path must be non-empty and relative: {path:?}");
    }
    if value
        .components()
        .any(|component| !matches!(component, Component::Normal(_)))
    {
        bail!("mutation path contains unsafe components: {path:?}");
    }
    Ok(())
}

/// Validate and optionally execute a mutation plan with best-effort rollback.
pub fn apply_plan(plan: &MutationPlan, execute: bool) -> Result<ApplyJournal> {
    if plan.schema_version != 1 {
        bail!("unsupported mutation plan schema {}", plan.schema_version);
    }
    let root = Path::new(&plan.root)
        .canonicalize()
        .with_context(|| format!("cannot resolve plan root {}", plan.root))?;
    let mut destinations = HashSet::new();
    for operation in &plan.operations {
        validate_relative_path(&operation.source)?;
        validate_relative_path(&operation.destination)?;
        if operation.source == operation.destination {
            bail!("source and destination are identical: {}", operation.source);
        }
        if !destinations.insert(operation.destination.clone()) {
            bail!("duplicate destination in plan: {}", operation.destination);
        }
        let source = root.join(&operation.source);
        let destination = root.join(&operation.destination);
        if !source.is_file() {
            bail!("source is missing or not a file: {}", source.display());
        }
        if destination.exists() {
            bail!("destination already exists: {}", destination.display());
        }
    }

    let mut completed = Vec::new();
    if execute {
        for operation in &plan.operations {
            let source = root.join(&operation.source);
            let destination = root.join(&operation.destination);
            if let Some(parent) = destination.parent() {
                fs::create_dir_all(parent)?;
            }
            if let Err(error) = fs::rename(&source, &destination) {
                for rollback in completed.iter().rev() {
                    let rollback: &MutationOperation = rollback;
                    let _ = fs::rename(
                        root.join(&rollback.destination),
                        root.join(&rollback.source),
                    );
                }
                return Err(anyhow!(error)).with_context(|| {
                    format!(
                        "failed to move {} to {}; completed operations were rolled back",
                        source.display(),
                        destination.display()
                    )
                });
            }
            completed.push(operation.clone());
        }
    }
    Ok(ApplyJournal {
        schema_version: 1,
        root: root.to_string_lossy().nfc().collect(),
        executed: execute,
        operation_count: plan.operations.len(),
        completed,
    })
}

/// Load a plan, apply it, and optionally write its journal atomically.
pub fn apply_plan_file(
    plan_path: &Path,
    journal_path: Option<&Path>,
    execute: bool,
) -> Result<String> {
    let plan: MutationPlan = serde_json::from_reader(
        File::open(plan_path)
            .with_context(|| format!("cannot open plan {}", plan_path.display()))?,
    )
    .with_context(|| format!("invalid plan JSON {}", plan_path.display()))?;
    let journal = apply_plan(&plan, execute)?;
    let payload = serde_json::to_string_pretty(&journal)?;
    if let Some(path) = journal_path {
        atomic_write(path, payload.as_bytes())?;
    }
    Ok(payload)
}

fn atomic_write(path: &Path, contents: &[u8]) -> Result<()> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let file_name = path
        .file_name()
        .ok_or_else(|| anyhow!("output path has no file name"))?
        .to_string_lossy();
    let temporary = parent.join(format!(".{file_name}.tmp-{}", std::process::id()));
    {
        let mut file = File::create(&temporary)?;
        file.write_all(contents)?;
        file.sync_all()?;
    }
    fs::rename(&temporary, path)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_sony_tmk_markers_as_minute_offsets() {
        let values = parse_tmk_markers(b"\xef\xbb\xbf[00005:00.01]\r\n[00075:02.50]\r\n");
        assert_eq!(values, vec![300.01, 4502.5]);
    }

    #[test]
    fn infers_location_from_multiline_and_plain_names() {
        assert_eq!(
            infer_location(
                "2024-07-29T13:58:35+09:00 대한민국\n서울특별시\n당산동5가 9-11\n07213 37.5 126.8.m4a"
            ),
            Some("당산동5가 9-11".to_string())
        );
        assert_eq!(
            infer_location("양평동4가 8.m4a"),
            Some("양평동4가".to_string())
        );
        assert_eq!(infer_location("251125_0905_02.wav"), None);
    }

    #[test]
    fn normalizes_copy_suffix_for_sidecars() {
        assert_eq!(
            sidecar_key(Path::new("FOLDER01/231018_1018(1).wav"), true),
            "FOLDER01\u{0}231018_1018"
        );
    }

    #[test]
    fn rejects_unsafe_mutation_paths() {
        assert!(validate_relative_path("recordings/a.wav").is_ok());
        assert!(validate_relative_path("../escape.wav").is_err());
        assert!(validate_relative_path("/absolute.wav").is_err());
        assert!(validate_relative_path("").is_err());
    }

    #[test]
    fn inspects_one_file_without_a_library_rescan() {
        let root =
            std::env::temp_dir().join(format!("codec-carver-core-inspect-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("240102_0304.wav"), b"audio").unwrap();
        let record = inspect_relative(&root, Path::new("240102_0304.wav")).unwrap();
        assert_eq!(record.kind, FileKind::Audio);
        assert_eq!(
            record.sha256.as_deref(),
            Some("6ed8919ce20490a5e3ad8630a4fab69475297abd07db73918dd5f36fcfaeb11b")
        );
        assert!(
            record
                .recorded_at
                .as_deref()
                .unwrap()
                .starts_with("2024-01-02T03:04")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn stages_and_hashes_one_file_in_a_single_stream() {
        let base =
            std::env::temp_dir().join(format!("codec-carver-core-stage-{}", std::process::id()));
        let root = base.join("library");
        let staging = base.join("staging");
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("240102_0304.wav"), b"audio").unwrap();
        let result = stage_relative(&root, Path::new("240102_0304.wav"), &staging).unwrap();
        assert_eq!(
            result.record.sha256.as_deref(),
            Some("6ed8919ce20490a5e3ad8630a4fab69475297abd07db73918dd5f36fcfaeb11b")
        );
        assert_eq!(fs::read(&result.staged_path).unwrap(), b"audio");
        let repeated = stage_relative(&root, Path::new("240102_0304.wav"), &staging).unwrap();
        assert_eq!(repeated.staged_path, result.staged_path);
        fs::remove_dir_all(base).unwrap();
    }
}

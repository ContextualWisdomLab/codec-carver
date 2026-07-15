use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};

#[derive(Debug, Parser)]
#[command(name = "codec-carver-core", version, about)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Hash and inventory an audio library, including Sony TMK sidecars.
    Inventory {
        #[arg(long)]
        root: PathBuf,
        #[arg(long)]
        output: Option<PathBuf>,
        #[arg(long)]
        threads: Option<usize>,
    },
    /// Hash and inspect one already-materialized file relative to a library root.
    Inspect {
        #[arg(long)]
        root: PathBuf,
        #[arg(long)]
        path: PathBuf,
    },
    /// Stream a dataless file to local scratch storage while hashing it.
    Stage {
        #[arg(long)]
        root: PathBuf,
        #[arg(long)]
        path: PathBuf,
        #[arg(long)]
        staging_dir: PathBuf,
    },
    /// Validate or execute a rename/quarantine plan.
    Apply {
        #[arg(long)]
        plan: PathBuf,
        #[arg(long)]
        journal: Option<PathBuf>,
        #[arg(long)]
        execute: bool,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let payload = match cli.command {
        Command::Inventory {
            root,
            output,
            threads,
        } => codec_carver_core::inventory_to_json(&root, output.as_deref(), threads)?,
        Command::Inspect { root, path } => {
            codec_carver_core::inspect_relative_to_json(&root, &path)?
        }
        Command::Stage {
            root,
            path,
            staging_dir,
        } => codec_carver_core::stage_relative_to_json(&root, &path, &staging_dir)?,
        Command::Apply {
            plan,
            journal,
            execute,
        } => codec_carver_core::apply_plan_file(&plan, journal.as_deref(), execute)?,
    };
    println!("{payload}");
    Ok(())
}

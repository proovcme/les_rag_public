//! Bounded diagnostic child processes; no service lifecycle ownership.

use std::{
    io::{self, Read},
    process::{Command, Output, Stdio},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

const MAX_STDOUT: usize = 512 * 1024;

pub fn output(command: &mut Command, timeout: Duration) -> io::Result<Output> {
    let deadline = Instant::now() + timeout;
    let mut child = command.stdin(Stdio::null()).stdout(Stdio::piped())
        .stderr(Stdio::null()).spawn()?;
    let stdout = child.stdout.take().expect("stdout was configured as piped");
    let (send, receive) = mpsc::channel();
    let reader = thread::Builder::new().name("les-setup-probe-stdout".into()).spawn(move || {
        let mut bytes = Vec::new();
        let result = stdout.take((MAX_STDOUT + 1) as u64).read_to_end(&mut bytes)
            .and_then(|_| {
                if bytes.len() > MAX_STDOUT {
                    Err(io::Error::new(io::ErrorKind::InvalidData, "setup probe stdout exceeds 512KiB"))
                } else {
                    Ok(bytes)
                }
            });
        let _ = send.send(result); // caller may already have timed out
    });
    let result = (|| {
        reader?;
        let mut captured = None;
        loop {
            if captured.is_none() {
                match receive.try_recv() {
                    Ok(result) => captured = Some(result?),
                    Err(mpsc::TryRecvError::Empty) => {},
                    Err(mpsc::TryRecvError::Disconnected) => {
                        return Err(io::Error::new(io::ErrorKind::BrokenPipe, "setup probe reader stopped"));
                    }
                }
            }
            if let Some(status) = child.try_wait()? {
                if let Some(stdout) = captured.take() {
                    return Ok(Output { status, stdout, stderr: Vec::new() });
                }
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(io::Error::new(io::ErrorKind::TimedOut, "setup probe deadline exceeded"));
            }
            thread::sleep(remaining.min(Duration::from_millis(10)));
        }
    })();
    if result.is_err() {
        // Own only this short-lived CLI child, never the provider service or process tree.
        child.kill()?;
        child.wait()?;
    }
    // Do not join a pipe reader: a provider-spawned descendant could retain its write handle.
    result
}

#[cfg(test)]
mod tests {
    use std::{io::{self, Write}, process::Command, time::{Duration, Instant}};

    fn child(mode: &str) -> Command {
        let mut command = Command::new(std::env::current_exe().unwrap());
        let test_path = format!("{}::probe_child", module_path!().split_once("::").unwrap().1);
        command.args(["--exact", &test_path, "--ignored", "--nocapture"])
            .env("LES_TEST_PROBE_MODE", mode);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0800_0000);
        }
        command
    }

    #[test]
    #[ignore = "owned child fixture, invoked by the process tests"]
    fn probe_child() {
        match std::env::var("LES_TEST_PROBE_MODE").unwrap().as_str() {
            "ok" => println!("NAME ID SIZE\nqwen:latest abc 20GB"),
            "fail" => std::process::exit(7),
            "large" => io::stdout().write_all(&vec![b'x'; 256 * 1024]).unwrap(),
            "overflow" => io::stdout().write_all(&vec![b'x'; 600 * 1024]).unwrap(),
            "hang" => std::thread::sleep(Duration::from_secs(60)),
            mode => panic!("unknown test mode {mode}"),
        }
    }

    #[test]
    fn captures_successful_output() {
        let result = super::output(&mut child("ok"), Duration::from_secs(3)).unwrap();
        assert!(result.status.success());
        assert!(String::from_utf8(result.stdout).unwrap().contains("qwen:latest abc 20GB"));
    }

    #[test]
    fn preserves_failure_status() {
        let result = super::output(&mut child("fail"), Duration::from_secs(3)).unwrap();
        assert_eq!(result.status.code(), Some(7));
    }

    #[test]
    fn drains_more_than_a_pipe_buffer() {
        let result = super::output(&mut child("large"), Duration::from_secs(3)).unwrap();
        assert!(result.status.success());
        assert!(result.stdout.windows(256 * 1024).any(|s| s.iter().all(|b| *b == b'x')));
    }

    #[test]
    fn rejects_oversized_output() {
        let error = super::output(&mut child("overflow"), Duration::from_secs(3)).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    }

    #[test]
    fn terminates_hanging_owned_child_within_budget() {
        let started = Instant::now();
        let error = super::output(&mut child("hang"), Duration::from_millis(80)).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::TimedOut);
        assert!(started.elapsed() < Duration::from_secs(4));
    }

    #[test]
    fn unknown_executable_is_an_error() {
        assert!(super::output(&mut Command::new("LES-nonexistent-probe-executable"),
                             Duration::from_secs(1)).is_err());
    }
}

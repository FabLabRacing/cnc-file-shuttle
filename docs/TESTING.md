# Development Test Checklist

## Local-folder regression

1. Load an existing local-folder profile from the earlier build.
2. Add two small `.ngc` files.
3. Change the target subfolder and confirm both pending paths update.
4. Send the queue and confirm both files arrive.
5. Send again and exercise Skip, Overwrite, Skip All, and Overwrite All.

## Saved overwrite policy

1. Set **If file exists** to **Always overwrite**, save the profile, reload it,
   and confirm the setting is retained.
2. Resend a file that already exists and confirm it is replaced without a
   prompt.
3. Set the option to **Skip existing**, save and reload the profile, then resend
   the file and confirm it is skipped without a prompt.
4. Set the option back to **Ask each time** and confirm the overwrite dialog
   returns.
5. With LinuxCNC running a program, set **Always overwrite** and confirm that an
   attempted overwrite of that exact active path is still blocked.

## Requeue and destination browser

1. Complete a queue containing at least two files, then press **Requeue
   Finished** and confirm the files return to Pending without disappearing.
2. Change the destination first, requeue the files, and confirm their target
   previews use the newly selected folder.
3. For a local profile, press Destination **Browse...**, select a subfolder of
   the profile root, and confirm Target subfolder becomes a relative path.
4. Try to select a folder outside the local profile root and confirm it is
   rejected.
5. For an SFTP profile, press Destination **Browse...**, navigate with Open,
   double-click, and Up, then choose **Select This Folder**.
6. Confirm the SFTP browser cannot navigate above the configured remote root.

## LinuxCNC SFTP preparation

The LinuxCNC computer needs its normal OpenSSH server running and the selected
user must be able to write to the configured program directory. No custom
receiver or LinuxCNC configuration changes are required.

From another computer, this should reach the same account:

```bash
ssh username@linuxcnc-ip
```

## Guided SSH-key setup

1. Create a new `SFTP / SSH` profile.
2. Enter host/IP, port, username, and the absolute remote program root.
3. Select **Set Up SSH Key...**.
4. Accept the default app-specific key filename.
5. For the first test, leave the key passphrase blank.
6. Compare the displayed host fingerprint with this command on LinuxCNC when
   practical:

   ```bash
   ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
   ```

7. Trust the host and enter the LinuxCNC account password once.
8. Confirm the app reports that key authentication was verified.
9. Save the profile.

## SFTP transfer

1. Select **Test Target** and confirm the remote folder is writable.
2. Add two test G-code files and send them.
3. Confirm progress is shown and the queue finishes with Done statuses.
4. Confirm the files are present under the exact displayed target paths.
5. Resend one file and test overwrite and skip choices.
6. Disconnect the LinuxCNC network temporarily and confirm the item fails,
   remains retryable, and produces a diagnostic log.

## LinuxCNC status monitoring

1. Launch the app with an SFTP profile saved first and confirm monitoring starts
   automatically without pressing **Connect / Monitor**.
2. Press **Disconnect** and confirm the app remains disconnected.
3. Select or reload an SFTP profile and confirm monitoring starts again.
4. With the LinuxCNC application closed, confirm **Controller Online** and
   **LinuxCNC Not Running** are shown separately.
5. Start LinuxCNC and check the E-stop, machine-off, and ready states.
6. Load and run a small test program. Confirm Program Running, its filename,
   and the executing line are shown.
7. Pause and resume the program and confirm the displayed state follows it.
8. While the test program is running, send a differently named file and confirm
   it succeeds.
9. Queue a file that would overwrite the active program path and confirm CNC
   File Shuttle blocks that item.
10. Press **Disconnect** and confirm monitoring stops without affecting LinuxCNC.

## Host-key protection

Use **Forget Host Trust...** only for this controlled test or after rebuilding
the LinuxCNC computer. Once forgotten, the next connection must display a new
first-connection trust prompt.

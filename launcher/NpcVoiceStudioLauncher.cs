using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;

internal static class NpcVoiceStudioLauncher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string installDirectory = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string launcherScript = Path.Combine(
            installDirectory,
            "scripts",
            "launch_npc_voice_studio.ps1"
        );
        string powershell = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe"
        );

        try
        {
            if (!File.Exists(launcherScript))
            {
                return Fail("The installed launcher script is missing.");
            }
            if (!File.Exists(powershell))
            {
                return Fail("Windows PowerShell is unavailable.");
            }

            StringBuilder arguments = new StringBuilder();
            AddArgument(arguments, "-STA");
            AddArgument(arguments, "-NoLogo");
            AddArgument(arguments, "-NoProfile");
            AddArgument(arguments, "-ExecutionPolicy");
            AddArgument(arguments, "Bypass");
            AddArgument(arguments, "-File");
            AddArgument(arguments, launcherScript);
            foreach (string argument in args)
            {
                AddArgument(arguments, argument);
            }

            ProcessStartInfo startInfo = new ProcessStartInfo
            {
                FileName = powershell,
                Arguments = arguments.ToString(),
                WorkingDirectory = installDirectory,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            };

            using (Process process = Process.Start(startInfo))
            {
                if (process == null)
                {
                    return Fail("Windows could not start the NPC Voice Studio launcher.");
                }
                process.WaitForExit();
                if (process.ExitCode != 0)
                {
                    AppendSetupLog("Launcher orchestration exited with code " + process.ExitCode + ".");
                }
                return process.ExitCode;
            }
        }
        catch (Exception exception)
        {
            return Fail("NPC Voice Studio could not start: " + exception.Message);
        }
    }

    private static void AddArgument(StringBuilder commandLine, string argument)
    {
        if (commandLine.Length > 0)
        {
            commandLine.Append(' ');
        }
        commandLine.Append('"');
        int backslashes = 0;
        foreach (char character in argument)
        {
            if (character == '\\')
            {
                backslashes++;
            }
            else if (character == '"')
            {
                commandLine.Append('\\', backslashes * 2 + 1);
                commandLine.Append('"');
                backslashes = 0;
            }
            else
            {
                commandLine.Append('\\', backslashes);
                commandLine.Append(character);
                backslashes = 0;
            }
        }
        commandLine.Append('\\', backslashes * 2);
        commandLine.Append('"');
    }

    private static int Fail(string message)
    {
        AppendSetupLog("ERROR: " + message);
        try
        {
            System.Windows.Forms.MessageBox.Show(
                message + Environment.NewLine + Environment.NewLine +
                "See the NPC Voice Studio setup log for details.",
                "NPC Voice Studio",
                System.Windows.Forms.MessageBoxButtons.OK,
                System.Windows.Forms.MessageBoxIcon.Error
            );
        }
        catch
        {
            // The setup log remains available if Windows cannot display a dialog.
        }
        return 1;
    }

    private static void AppendSetupLog(string message)
    {
        try
        {
            string logDirectory = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "NPC Voice Studio",
                "logs"
            );
            Directory.CreateDirectory(logDirectory);
            File.AppendAllText(
                Path.Combine(logDirectory, "setup.log"),
                DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + message + Environment.NewLine,
                Encoding.UTF8
            );
        }
        catch
        {
            // There is no safer fallback location that is guaranteed writable.
        }
    }
}

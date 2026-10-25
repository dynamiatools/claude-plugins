import json
import os
import subprocess
import sys
import unittest

GUARD = os.path.join(os.path.dirname(__file__), "..", "bin", "mysql-guard")


def run(cmd=None, tool="Bash", **ti):
    payload = {"tool_name": tool, "tool_input": ti if ti else {"command": cmd}}
    p = subprocess.run([sys.executable, GUARD], input=json.dumps(payload), capture_output=True, text=True)
    if p.returncode == 2:
        return "deny"
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"] if p.stdout.strip() else "allow"


class GuardTest(unittest.TestCase):
    def test_silent_outside_mysql(self):
        for c in ("ls -la", "git status", "rm -rf build", "systemctl restart nginx", "psql -c 'drop table x'", "npm test"):
            self.assertEqual(run(c), "allow", c)

    def test_reads_are_allowed(self):
        for c in ("mysql-tool query src \"SELECT 1\"", "mysql-tool replica-status rep", "mysql-tool inspect src",
                  "mysql -e 'SHOW REPLICA STATUS'", "mysqld --version", "git log --oneline -- mysql", "grep -r DROP mysql/"):
            self.assertEqual(run(c), "allow", c)

    def test_passwords_in_commands_are_denied(self):
        for c in ("mysql -u root -pSecret -e 'select 1'", "mysqldump --password=abc db", "MYSQL_PWD=x mysql -e 'select 1'",
                  "mysql-tool exec rep \"CREATE USER 'r'@'h' IDENTIFIED BY 'plain'\"",
                  "mysql -e \"CHANGE REPLICATION SOURCE TO SOURCE_PASSWORD='x'\""):
            self.assertEqual(run(c), "deny", c)

    def test_prompt_and_placeholder_passwords_are_not_denied_as_passwords(self):
        self.assertEqual(run("mysql -u root -p -e 'select 1'"), "allow")
        self.assertEqual(run("mysql -P 3306 -h x -e 'select 1'"), "allow")
        self.assertEqual(run("mysql-tool exec rep \"CREATE USER 'r'@'h' IDENTIFIED BY '@@ENV:REPL_PW@@'\""), "ask")

    def test_destructive_is_denied(self):
        for c in ("mysql -e 'DROP DATABASE shop'", "mysql -e 'truncate table t'", "mysql -e 'delete from t'",
                  "mysql -e 'update t set a=1'", "mysql -e 'RESET BINARY LOGS AND GTIDS'", "mysql -e 'RESET MASTER'",
                  "mysql -e \"PURGE BINARY LOGS BEFORE now()\"", "rm -rf /var/lib/mysql", "sudo rm -rf /var/lib/mariadb/data"):
            self.assertEqual(run(c), "deny", c)

    def test_critical_operations_ask(self):
        for c in ("systemctl restart mysql", "sudo systemctl stop mariadb", "mysqladmin shutdown",
                  "mv /var/lib/mysql /var/lib/mysql.old", "rsync -a /backup/ /var/lib/mysql/", "mysql db < dump.sql",
                  "zcat dump.sql.gz | mysql db", "xtrabackup --move-back --target-dir=/b", "mariadb-backup --copy-back --target-dir=/b",
                  "mysql-tool exec rep \"CLONE INSTANCE FROM 'c'@'h':3306 IDENTIFIED BY '@@ENV:CLONE_PW@@'\"",
                  "mysql-tool exec rep \"STOP REPLICA\"", "mysql-tool exec rep \"SET GLOBAL gtid_purged='x'\"",
                  "mysql -e 'ALTER TABLE t ADD c int'", "mysql -e \"DELETE FROM t WHERE id=1\"", "mysqld --initialize"):
            self.assertEqual(run(c), "ask", c)

    def test_secrets_file_is_protected(self):
        self.assertEqual(run("cat ~/.config/dynamia-mysql/secrets.env"), "deny")
        self.assertEqual(run(tool="Read", file_path="/home/u/.config/dynamia-mysql/secrets.env"), "deny")
        self.assertEqual(run(tool="Read", file_path="/home/u/app/main.py"), "allow")

    def test_fails_open_on_garbage(self):
        p = subprocess.run([sys.executable, GUARD], input="not json", capture_output=True, text=True)
        self.assertEqual((p.returncode, p.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MAX_FILENAME_BYTES,
  MAX_UPLOAD_MB,
  deriveTaskIdPreview,
  formatFileSize,
  validatePackageFile,
} from "./uploadPrecheck.ts";

describe("deriveTaskIdPreview", () => {
  it("与后端 clean_task_id 保持同一派生规则", () => {
    // 固定样例锁定后端 app/cli.py::generate_task_id 行为。
    assert.equal(deriveTaskIdPreview("ZZapp01BCN_app_Problem_scene_333.zip"), "task-zzapp01bcn_app_problem_scene_333");
    assert.equal(deriveTaskIdPreview("A B/C?.tar.gz"), "task-a_b_c");
    assert.equal(deriveTaskIdPreview("巡检数据.zip"), "task-task");
    assert.equal(deriveTaskIdPreview("___.zip"), "task-task");
    assert.equal(deriveTaskIdPreview("T2026-10-10.tgz"), "task-t2026_10_10");
  });

  it("大小写与多段扩展名归一化后结果稳定", () => {
    assert.equal(deriveTaskIdPreview("Report.ZIP"), deriveTaskIdPreview("report.zip"));
  });
});

describe("validatePackageFile", () => {
  it("合法压缩包通过全部校验", () => {
    const result = validatePackageFile({ name: "sample.zip", size: 1024 });
    assert.equal(result.valid, true);
    assert.equal(result.formatValid, true);
    assert.equal(result.sizeValid, true);
    assert.equal(result.nameValid, true);
    assert.deepEqual(result.messages, []);
  });

  it("扩展名不合法时给出具体原因", () => {
    const result = validatePackageFile({ name: "sample.rar", size: 1024 });
    assert.equal(result.valid, false);
    assert.equal(result.formatValid, false);
    assert.match(result.messages.join(" "), /格式|zip/);
  });

  it("空文件与超限文件被拒绝", () => {
    assert.match(
      validatePackageFile({ name: "empty.zip", size: 0 }).messages.join(" "),
      /空/,
    );
    const tooLarge = validatePackageFile({
      name: "huge.zip",
      size: (MAX_UPLOAD_MB + 1) * 1024 * 1024,
    });
    assert.equal(tooLarge.sizeValid, false);
    assert.match(tooLarge.messages.join(" "), new RegExp(String(MAX_UPLOAD_MB)));
  });

  it("文件名超过 255 字节时被拒绝", () => {
    const longName = `${"a".repeat(MAX_FILENAME_BYTES)}.zip`;
    const result = validatePackageFile({ name: longName, size: 1024 });
    assert.equal(result.nameValid, false);
    assert.match(result.messages.join(" "), /255/);
  });

  it("tar / tgz / gz 变体被接受", () => {
    for (const name of ["a.tar", "a.tgz", "a.gz", "a.tar.gz"]) {
      assert.equal(validatePackageFile({ name, size: 10 }).formatValid, true, name);
    }
  });

  it("无文件名时按格式不合法处理", () => {
    const result = validatePackageFile({ name: "", size: 10 });
    assert.equal(result.valid, false);
    assert.equal(result.formatValid, false);
  });
});

describe("formatFileSize", () => {
  it("按二进制单位输出可读文本", () => {
    assert.equal(formatFileSize(0), "0 B");
    assert.equal(formatFileSize(512), "512 B");
    assert.equal(formatFileSize(1024), "1 KB");
    assert.equal(formatFileSize(1024 * 1024 * 3), "3 MB");
  });

  it("非法数值回退占位符", () => {
    assert.equal(formatFileSize(Number.NaN), "-");
    assert.equal(formatFileSize(-1), "-");
  });
});

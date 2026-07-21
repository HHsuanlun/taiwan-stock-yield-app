import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const outputDir = "outputs/financial_dividend";
const file = `${outputDir}/台灣金融股_股利殖利率.xlsx`;
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(file));
for (const sheetName of ["總覽", "歷年股利", "資料來源與說明"]) {
  const png = await wb.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(`${outputDir}/${sheetName}.png`, new Uint8Array(await png.arrayBuffer()));
}

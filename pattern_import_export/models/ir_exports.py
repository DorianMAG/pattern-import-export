# Copyright 2020 Akretion France (http://www.akretion.com)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import base64
import traceback
from io import StringIO

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression

from odoo.addons.queue_job.job import job

from .common import COLUMN_X2M_SEPARATOR, IDENTIFIER_SUFFIX


class IrExports(models.Model):
    """
    Todo: description:
    Add selection options on field export_format
    To implements:
    _export_with_record_FORMAT (should use an iterator)
    _read_import_data_FORMAT (should return an iterator)
    """

    _inherit = "ir.exports"

    use_description = fields.Boolean(
        string="Use descriptive in addition to technical headers"
    )
    is_pattern = fields.Boolean()
    pattern_file = fields.Binary(string="Pattern file", readonly=True)
    pattern_file_name = fields.Char(readonly=True)
    pattern_last_generation_date = fields.Datetime(
        string="Pattern last generation date", readonly=True
    )
    export_format = fields.Selection(selection=[])
    partial_commit = fields.Boolean(
        default=True, help="Import data even if some lines fail to import"
    )
    flush_step = fields.Integer(default=500, help="Define the size of batch import")
    count_pattern_file_fail = fields.Integer(compute="_compute_pattern_file_counts")
    count_pattern_file_pending = fields.Integer(compute="_compute_pattern_file_counts")
    count_pattern_file_success = fields.Integer(compute="_compute_pattern_file_counts")
    pattern_file_ids = fields.One2many("pattern.file", "export_id")

    def _compute_pattern_file_counts(self):
        for rec in self:
            for state in ("fail", "pending", "success"):
                field_name = "count_pattern_file_" + state
                count = len(
                    rec.pattern_file_ids.filtered(lambda r: r.state == state).ids
                )
                setattr(rec, field_name, count)

    def _open_pattern_file(self, domain=None):
        if domain is None:
            domain = []
        domain = expression.AND([[("export_id", "=", self.id)], domain])
        return {
            "name": _("Pattern files"),
            "view_type": "form",
            "view_mode": "tree,form",
            "res_model": "pattern.file",
            "type": "ir.actions.act_window",
            "domain": domain,
        }

    def button_open_pattern_file_fail(self):
        return self._open_pattern_file([("state", "=", "fail")])

    def button_open_pattern_file_pending(self):
        return self._open_pattern_file([("state", "=", "pending")])

    def button_open_pattern_file_success(self):
        return self._open_pattern_file([("state", "=", "success")])

    @property
    def row_start_records(self):
        return self.nr_of_header_rows + 1

    @property
    def nr_of_header_rows(self):
        return 1 + int(self.use_description)

    @api.multi
    def _get_header(self, use_description=False):
        """
        Build header of data-structure.
        Could be recursive in case of lines with pattern_export_id.
        @return: list of string
        """
        self.ensure_one()
        header = []
        for export_line in self.export_fields:
            header.extend(export_line._get_header(use_description))
        return header

    @api.multi
    def generate_pattern(self):
        """
        Allows you to generate an (empty) file to be used a
        pattern for the export.
        @return: bool
        """
        for export in self:
            records = self.env[export.model_id.model].browse()
            data = export._generate_with_records(records)
            if data:
                data = data[0]
            filename = self.name + "." + self.export_format
            export.write(
                {
                    "pattern_file": data,
                    "pattern_last_generation_date": fields.Datetime.now(),
                    "pattern_file_name": filename,
                }
            )
        return True

    @api.multi
    def _get_data_to_export(self, records):
        """
        Iterator who built data dict record by record.
        This function could be recursive in case of sub-pattern
        """
        self.ensure_one()
        json_parser = self.export_fields._get_json_parser_for_pattern()
        for record in records:
            yield self._get_data_to_export_by_record(record, json_parser)

    def json2pattern_format(self, data):
        res = {}
        for header in self._get_header():
            try:
                val = data
                for key in header.split(COLUMN_X2M_SEPARATOR):
                    if key.isdigit():
                        key = int(key) - 1
                    elif IDENTIFIER_SUFFIX in key:
                        key = key.replace(IDENTIFIER_SUFFIX, "")
                    if key == ".id":
                        key = "id"
                    val = val[key]
                    if val is None:
                        break
            except IndexError:
                val = None
            res[header] = val
        return res

    @api.multi
    def _get_data_to_export_by_record(self, record, parser):
        """
        Use the ORM cache to re-use already exported data and
        could also prevent infinite recursion
        @param record: recordset
        @return: dict
        """
        self.ensure_one()
        record.ensure_one()
        data = record.jsonify(parser)[0]
        return self.json2pattern_format(data)

    @api.multi
    def _generate_with_records(self, records):
        """
        Export given recordset
        @param records: recordset
        @return: list of base64 encoded
        """
        all_data = []
        for export in self:
            target_function = "_export_with_record_{format}".format(
                format=export.export_format or ""
            )
            if not export.export_format or not hasattr(export, target_function):
                msg = "The export with the format {format} doesn't exist!".format(
                    format=export.export_format or "Undefined"
                )
                raise NotImplementedError(msg)
            export_data = getattr(export, target_function)(records)
            if export_data:
                all_data.append(base64.b64encode(export_data))
        return all_data

    @api.multi
    def _export_with_record(self, records):
        """
        Export given recordset
        @param records: recordset
        @return: ir.attachment recordset
        """
        pattern_file_exports = self.env["pattern.file"]
        all_data = self._generate_with_records(records)
        if all_data and self.env.context.get("export_as_attachment", True):
            for export, attachment_data in zip(self, all_data):
                pattern_file_exports |= export._create_pattern_file_export(
                    attachment_data
                )
        return pattern_file_exports

    def _create_pattern_file_export(self, attachment_datas):
        """
        Attach given parameter (b64 encoded) to the current export.
        @param attachment_datas: base64 encoded data
        @return: ir.attachment recordset
        """
        self.ensure_one()
        name = "{name}.{format}".format(name=self.name, format=self.export_format)
        return self.env["pattern.file"].create(
            {
                "name": name,
                "type": "binary",
                "res_id": self.id,
                "res_model": "ir.exports",
                "datas": attachment_datas,
                "datas_fname": name,
                "kind": "export",
                "state": "success",
                "export_id": self.id,
            }
        )

    # Import part

    @api.multi
    def _read_import_data(self, datafile):
        """

        @param datafile:
        @return: list of str
        """
        target_function = "_read_import_data_{format}".format(
            format=self.export_format or ""
        )
        if not hasattr(self, target_function):
            raise NotImplementedError()
        return getattr(self, target_function)(datafile)

    def _process_load_message(self, messages):
        count_errors = 0
        count_warnings = 0
        error_message = _(
            "\n Several error have been found "
            "number of errors: {}, number of warnings: {}"
            "\nDetail:\n {}"
        )
        error_details = []
        for message in messages:
            error_details.append(
                _("Line {} : {}, {}").format(
                    message["rows"]["to"], message["type"], message["message"]
                )
            )
            if message["type"] == "error":
                count_errors += 1
            elif message["type"] == "warning":
                count_warnings += 1
            else:
                raise UserError(
                    _("Message type {} is not supported").format(message["type"])
                )
        if count_errors or count_warnings:
            return error_message.format(
                count_errors, count_warnings, "\n".join(error_details)
            )
        return ""

    def _process_load_result(self, pattern_file_import, res):
        ids = res["ids"] or []
        info = _("Number of record imported {}").format(len(ids))
        info_detail = _("Details: {}".format(ids))
        if res.get("messages"):
            info += self._process_load_message(res["messages"])
        if res.get("messages"):
            state = "fail"
        else:
            state = "success"
        return info, info_detail, state

    @job(default_channel="root.importwithpattern")
    def _generate_import_with_pattern_job(self, pattern_file_import):
        try:
            attachment_data = base64.b64decode(
                pattern_file_import.datas.decode("utf-8")
            )
            datas = self._read_import_data(attachment_data)
        except Exception as e:
            pattern_file_import.state = "fail"
            pattern_file_import.info = _("Failed (check details)")
            pattern_file_import.info_detail = e
        try:
            res = (
                self.with_context(
                    pattern_config={
                        "model": self.model_id.model,
                        "flush_step": self.flush_step,
                        "partial_commit": self.partial_commit,
                    }
                )
                .env[self.model_id.model]
                .load([], datas)
            )
            (
                pattern_file_import.info,
                pattern_file_import.info_detail,
                pattern_file_import.state,
            ) = self._process_load_result(pattern_file_import, res)
        except Exception:
            buff = StringIO()
            traceback.print_exc(file=buff)
            pattern_file_import.state = "fail"
            pattern_file_import.info = "Failed To load (check details)"
            pattern_file_import.info_detail = buff.getvalue()
        return

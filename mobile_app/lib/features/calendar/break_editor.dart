import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'calendar_models.dart';

class BreakDraft {
  const BreakDraft({
    required this.date,
    required this.startTime,
    required this.endTime,
    required this.label,
  });

  final String date;
  final String startTime;
  final String endTime;
  final String label;
}

class BreakEditor extends StatefulWidget {
  const BreakEditor({
    required this.initialDate,
    this.item,
    super.key,
  });

  final DateTime initialDate;
  final CalendarBreak? item;

  @override
  State<BreakEditor> createState() => _BreakEditorState();
}

class _BreakEditorState extends State<BreakEditor> {
  late DateTime _date;
  late TimeOfDay _start;
  late final TextEditingController _labelController;
  late final TextEditingController _durationController;
  final _formKey = GlobalKey<FormState>();

  @override
  void initState() {
    super.initState();
    final item = widget.item;
    _date = DateTime.tryParse(item?.date ?? '') ?? widget.initialDate;
    final startParts = (item?.startTime ?? '12:00').split(':');
    final endParts = (item?.endTime ?? '13:00').split(':');
    _start = TimeOfDay(
      hour: int.tryParse(startParts[0]) ?? 12,
      minute: startParts.length > 1 ? int.tryParse(startParts[1]) ?? 0 : 0,
    );
    var duration = ((int.tryParse(endParts[0]) ?? 13) * 60 +
            (endParts.length > 1 ? int.tryParse(endParts[1]) ?? 0 : 0)) -
        (_start.hour * 60 + _start.minute);
    if (duration <= 0) duration = 60;
    _durationController = TextEditingController(text: duration.toString());
    _labelController = TextEditingController(text: item?.label ?? 'Зайнято');
  }

  @override
  void dispose() {
    _labelController.dispose();
    _durationController.dispose();
    super.dispose();
  }

  Future<void> _chooseDate() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime(2020),
      lastDate: DateTime(2035),
    );
    if (date != null) setState(() => _date = date);
  }

  Future<void> _chooseTime() async {
    final time = await showTimePicker(context: context, initialTime: _start);
    if (time != null) setState(() => _start = time);
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) return;
    final startMinutes = _start.hour * 60 + _start.minute;
    final duration = int.parse(_durationController.text.trim());
    final endMinutes = startMinutes + duration;
    if (endMinutes > 24 * 60) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Зайнятий час не може перейти на наступну добу')),
      );
      return;
    }
    String clock(int minutes) =>
        '${(minutes ~/ 60).toString().padLeft(2, '0')}:${(minutes % 60).toString().padLeft(2, '0')}';
    Navigator.of(context).pop(
      BreakDraft(
        date: DateFormat('yyyy-MM-dd').format(_date),
        startTime: clock(startMinutes),
        endTime: clock(endMinutes),
        label: _labelController.text.trim().isEmpty ? 'Зайнято' : _labelController.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(widget.item == null ? 'Зайнятий час' : 'Редагувати блокування'),
        content: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _labelController,
                decoration: const InputDecoration(labelText: 'Назва'),
              ),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: _chooseDate,
                      icon: const Icon(Icons.calendar_today),
                      label: Text(DateFormat('dd.MM.yyyy').format(_date)),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: _chooseTime,
                      icon: const Icon(Icons.schedule),
                      label: Text(_start.format(context)),
                    ),
                  ),
                ],
              ),
              TextFormField(
                controller: _durationController,
                decoration: const InputDecoration(labelText: 'Тривалість, хв'),
                keyboardType: TextInputType.number,
                validator: (value) {
                  final parsed = int.tryParse(value?.trim() ?? '');
                  return parsed == null || parsed < 5 || parsed > 600
                      ? 'Вкажіть від 5 до 600 хвилин'
                      : null;
                },
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Скасувати')),
          FilledButton(onPressed: _submit, child: const Text('Зберегти')),
        ],
      );
}

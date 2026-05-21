/**
 * 研发会议室统一人机确认表单（问答 / 选择 / 填写）。
 * 可由配置 schema 驱动，也可在会议室介入弹窗中只读预览或提交。
 */
import React, { useMemo } from 'react';
import { Input, Radio, Select, Checkbox, Form, Button } from 'antd';

const { TextArea } = Input;

export type HitlFieldType = 'text' | 'textarea' | 'select' | 'radio' | 'checkbox';

export interface HitlFormFieldOption {
  label: string;
  value: string;
}

export interface HitlFormField {
  id: string;
  label: string;
  type: HitlFieldType;
  required?: boolean;
  placeholder?: string;
  options?: HitlFormFieldOption[];
}

export interface HitlFormSchema {
  title?: string;
  description?: string;
  fields: HitlFormField[];
}

export type HitlFormValues = Record<string, string | string[] | boolean>;

export const MeetingHitlForm: React.FC<{
  schema: HitlFormSchema;
  /** 待确认总结（人工确认门控：归档前展示） */
  summaryMarkdown?: string;
  /** 预览模式：仅展示字段结构，不可提交 */
  preview?: boolean;
  initialValues?: HitlFormValues;
  onSubmit?: (values: HitlFormValues) => void;
  submitLabel?: string;
  className?: string;
}> = ({
  schema,
  summaryMarkdown,
  preview = false,
  initialValues,
  onSubmit,
  submitLabel = '提交确认',
  className = '',
}) => {
  const [form] = Form.useForm<HitlFormValues>();

  const fields = useMemo(
    () => (Array.isArray(schema.fields) ? schema.fields : []),
    [schema.fields],
  );

  const renderField = (field: HitlFormField) => {
    const rules = field.required
      ? [{ required: true, message: `请填写${field.label}` }]
      : [];
    const common = { name: field.id, label: field.label, rules };

    switch (field.type) {
      case 'textarea':
        return (
          <Form.Item key={field.id} {...common}>
            <TextArea
              rows={3}
              disabled={preview}
              placeholder={field.placeholder}
              className="bg-muted/20 border-border/50 text-foreground text-xs"
            />
          </Form.Item>
        );
      case 'select':
        return (
          <Form.Item key={field.id} {...common}>
            <Select
              disabled={preview}
              placeholder={field.placeholder || '请选择'}
              options={(field.options || []).map((o) => ({
                value: o.value,
                label: o.label,
              }))}
              className="w-full"
            />
          </Form.Item>
        );
      case 'radio':
        return (
          <Form.Item key={field.id} {...common}>
            <Radio.Group disabled={preview}>
              {(field.options || []).map((o) => (
                <Radio key={o.value} value={o.value} className="text-foreground text-xs">
                  {o.label}
                </Radio>
              ))}
            </Radio.Group>
          </Form.Item>
        );
      case 'checkbox':
        return (
          <Form.Item
            key={field.id}
            name={field.id}
            valuePropName="checked"
            label={field.label}
            rules={rules}
          >
            <Checkbox disabled={preview} className="text-foreground text-xs">
              {field.placeholder || field.label}
            </Checkbox>
          </Form.Item>
        );
      default:
        return (
          <Form.Item key={field.id} {...common}>
            <Input
              disabled={preview}
              placeholder={field.placeholder}
              className="bg-muted/20 border-border/50 text-foreground text-xs"
            />
          </Form.Item>
        );
    }
  };

  return (
    <div className={`rd-meeting-hitl-form rounded-lg border border-border/60 bg-muted/20 p-3 ${className}`}>
      {schema.title ? (
        <div className="text-xs font-medium text-foreground/90 mb-1">{schema.title}</div>
      ) : null}
      {schema.description ? (
        <p className="text-[11px] text-muted-foreground leading-relaxed mb-3">{schema.description}</p>
      ) : null}
      {summaryMarkdown && !preview ? (
        <div className="mb-3 rounded-md border border-border/50 bg-background/60 p-3 max-h-48 overflow-y-auto custom-scrollbar">
          <div className="text-[10px] font-medium text-muted-foreground mb-2">待确认总结</div>
          <pre className="text-[11px] text-foreground/90 whitespace-pre-wrap font-sans leading-relaxed m-0">
            {summaryMarkdown}
          </pre>
        </div>
      ) : null}
      <Form
        form={form}
        layout="vertical"
        initialValues={initialValues}
        onFinish={(values) => onSubmit?.(values)}
        className="rd-meeting-hitl-form-inner"
      >
        {fields.map(renderField)}
        {!preview && onSubmit ? (
          <Button type="primary" htmlType="submit" size="small" className="mt-1">
            {submitLabel}
          </Button>
        ) : null}
      </Form>
      {preview ? (
        <p className="text-[10px] text-muted-foreground mt-2 mb-0">
          预览：节点开启「人工确认」后，智能体先输出待确认总结，用户审阅并填写上述字段提交；确认通过后系统才写入归档产物并推进节点。
        </p>
      ) : null}
    </div>
  );
};

import { FileTextOutlined, CodeOutlined } from '@ant-design/icons';
import { useMemo } from 'react';
import { useDashboard } from '@rd-view/context/DashboardContext';
import { getProductAssistantOutputByTimeRange } from '@rd-view/data/mockData';
import { TIME_RANGE_LABEL } from '@rd-view/utils/assistantOutput';

function ProductOutputCard({
  productName,
  docCount,
  codeCount,
}: {
  productName: string;
  docCount: number;
  codeCount: number;
}) {
  return (
    <div className="assistant-output-product-card">
      <div className="assistant-output-product-name" title={productName}>
        {productName}
      </div>
      <div className="assistant-output-product-metrics">
        <span className="assistant-output-metric assistant-output-metric--doc">
          <FileTextOutlined />
          文档 {docCount}
        </span>
        <span className="assistant-output-metric assistant-output-metric--code">
          <CodeOutlined />
          代码 {codeCount}
        </span>
      </div>
    </div>
  );
}

export function AssistantOutputPopoverContent() {
  const { state } = useDashboard();

  const products = useMemo(
    () => getProductAssistantOutputByTimeRange(state.timeRange),
    [state.timeRange],
  );

  return (
    <div className="efficiency-popover assistant-output-popover">
      <div className="efficiency-popover-header">
        研发助手产出明细（{TIME_RANGE_LABEL[state.timeRange]}）
      </div>
      <div className="assistant-output-product-grid">
        {products.map((item) => (
          <ProductOutputCard
            key={item.productName}
            productName={item.productName}
            docCount={item.docCount}
            codeCount={item.codeCount}
          />
        ))}
      </div>
    </div>
  );
}

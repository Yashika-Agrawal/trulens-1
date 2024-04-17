import { useEffect, useState } from 'react';
import KeyboardArrowDownRounded from '@mui/icons-material/KeyboardArrowDownRounded';
import KeyboardArrowUpRounded from '@mui/icons-material/KeyboardArrowUpRounded';
import { Box, Grid, Stack, Typography, gridClasses } from '@mui/material';
import { SimpleTreeView } from '@mui/x-tree-view';
import { Streamlit } from 'streamlit-component-lib';
import { AppJSONRaw, RecordJSONRaw, StackTreeNode } from '../utils/types';
import { getStartAndEndTimesForNode } from '../utils/treeUtils';
import RecordTreeCellRecursive from './RecordTreeCellRecursive';
import { Tabs, Tab } from '../Tabs';
import { ROOT_NODE_ID } from '../utils/utils';
import Details from './Details/Details';
import JSONViewer from '../JSONViewer/JSONViewer';
import RecordTable from '../RecordTable/RecordTable';

enum RECORD_CONTENT_TABS {
  DETAILS = 'Details',
  SPAN_JSON = 'Span JSON',
  RECORD_JSON = 'Record JSON',
  APP_JSON = 'App JSON',
  RECORD_METADATA = 'Metadata',
}

const SPAN_TREE_TABS = [RECORD_CONTENT_TABS.DETAILS, RECORD_CONTENT_TABS.SPAN_JSON];

const GENERAL_TABS = [
  RECORD_CONTENT_TABS.RECORD_METADATA,
  RECORD_CONTENT_TABS.RECORD_JSON,
  RECORD_CONTENT_TABS.APP_JSON,
];

enum SPAN_VIEW {
  TREE = 'Tree',
  TIMELINE = 'Timeline',
}

const SPAN_VIEWS = [SPAN_VIEW.TREE, SPAN_VIEW.TIMELINE];

type RecordTreeProps = {
  appJSON: AppJSONRaw;
  nodeMap: Record<string, StackTreeNode>;
  recordJSON: RecordJSONRaw;
  root: StackTreeNode;
};

export default function RecordTree({ appJSON, nodeMap, recordJSON, root }: RecordTreeProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedSpanView, setSelectedSpanView] = useState<SPAN_VIEW>(SPAN_VIEW.TREE);
  const [selectedTab, setSelectedTab] = useState<RECORD_CONTENT_TABS>(RECORD_CONTENT_TABS.DETAILS);

  const handleItemSelectionToggle = (_event: React.SyntheticEvent, itemId: string, isSelected: boolean) => {
    if (isSelected) {
      setSelectedNodeId(itemId);
    } else {
      setSelectedNodeId(null);
    }
  };
  const selectedNode = selectedNodeId ? nodeMap[selectedNodeId] : root;

  useEffect(() => Streamlit.setComponentValue(selectedNode?.raw?.perf?.start_time ?? ''), [selectedNode]);

  const { timeTaken: totalTime, startTime: treeStart } = getStartAndEndTimesForNode(root);

  const getSelectedView = () => {
    if (selectedTab === RECORD_CONTENT_TABS.APP_JSON) {
      return <JSONViewer src={appJSON} />;
    }

    if (selectedTab === RECORD_CONTENT_TABS.SPAN_JSON) {
      return <JSONViewer src={selectedNodeId === ROOT_NODE_ID ? recordJSON : selectedNode.raw ?? {}} />;
    }

    if (selectedTab === RECORD_CONTENT_TABS.RECORD_JSON) {
      return <JSONViewer src={recordJSON} />;
    }

    if (selectedTab === RECORD_CONTENT_TABS.RECORD_METADATA) {
      const { meta } = recordJSON;
      if (!meta || !Object.keys(meta as object)?.length) return <Typography>No record metadata available.</Typography>;

      if (typeof meta === 'object') {
        return <JSONViewer src={meta as object} />;
      }

      return (
        <Typography>Invalid metadata type. Expected a dictionary but got {String(meta) ?? 'unknown object'}</Typography>
      );
    }

    return <Details selectedNode={selectedNode} recordJSON={recordJSON} />;
  };

  return (
    <Grid
      container
      sx={{
        border: ({ palette }) => `0.5px solid ${palette.grey[300]}`,
        borderRadius: 0.5,
        [`& .${gridClasses.item}`]: {
          border: ({ palette }) => `0.5px solid ${palette.grey[300]}`,
        },
      }}
    >
      <Grid item xs={12} sm={selectedSpanView === SPAN_VIEW.TIMELINE ? 12 : 4}>
        <Tabs
          value={selectedSpanView}
          onChange={(_event, value) => setSelectedSpanView(value as SPAN_VIEW)}
          sx={{ borderBottom: ({ palette }) => `1px solid ${palette.grey[300]}` }}
        >
          {SPAN_VIEWS.map((tab) => (
            <Tab label={tab} value={tab} key={tab} id={tab} />
          ))}
        </Tabs>

        {selectedSpanView === SPAN_VIEW.TIMELINE ? (
          <RecordTable selectedNodeId={selectedNodeId} setSelectedNodeId={setSelectedNodeId} root={root} />
        ) : (
          <SimpleTreeView
            sx={{ p: 1, overflowY: 'auto', flexGrow: 0 }}
            slots={{
              collapseIcon: KeyboardArrowUpRounded,
              expandIcon: KeyboardArrowDownRounded,
            }}
            onExpandedItemsChange={() => {
              setTimeout(() => Streamlit.setFrameHeight(), 300);
            }}
            defaultSelectedItems={selectedNodeId ?? ROOT_NODE_ID}
            defaultExpandedItems={Object.keys(nodeMap) ?? []}
            onItemSelectionToggle={handleItemSelectionToggle}
          >
            <RecordTreeCellRecursive node={root} depth={0} totalTime={totalTime} treeStart={treeStart} />
          </SimpleTreeView>
        )}
      </Grid>

      <Grid item xs={12} sm={selectedSpanView === SPAN_VIEW.TIMELINE ? 12 : 8}>
        <Tabs
          value={selectedTab}
          onChange={(_event, value) => setSelectedTab(value as RECORD_CONTENT_TABS)}
          sx={{ borderBottom: ({ palette }) => `1px solid ${palette.grey[300]}` }}
        >
          {SPAN_TREE_TABS.map((tab) => (
            <Tab label={tab} value={tab} key={tab} id={tab} />
          ))}
          <Box sx={{ flexGrow: 1 }} />
          {GENERAL_TABS.map((tab) => (
            <Tab label={tab} value={tab} key={tab} id={tab} />
          ))}
        </Tabs>

        <Stack gap={2} sx={{ flexGrow: 1, p: 1, mb: 4 }}>
          {getSelectedView()}
        </Stack>
      </Grid>
    </Grid>
  );
}
